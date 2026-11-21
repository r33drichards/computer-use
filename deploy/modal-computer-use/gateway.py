"""MCP-only ASGI gateway. The hosted desktop never receives auth headers."""
import asyncio
import hashlib
import hmac
import re
from contextlib import asynccontextmanager

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from runtime import (BROWSER, BROWSER_STATE, DESKTOP_UID, MCP, MCP_STATE, MCP_UID,
                     desktop_env, mcp_env, prepare_files, start_unprivileged,
                     terminate, wait_ready)

REQUEST_HEADERS = {"accept", "content-type", "mcp-session-id", "mcp-protocol-version", "last-event-id"}
RESPONSE_HEADERS = {"content-type", "mcp-session-id", "mcp-protocol-version", "cache-control", "allow", "retry-after"}
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_SECONDS = 105


def bearer_digest_matches(values: list[str], digest: str) -> bool:
    if len(values) != 1:
        return False
    scheme, _, token = values[0].partition(" ")
    if scheme.lower() != "bearer" or not re.fullmatch(r"[A-Fa-f0-9]{64}", token):
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode("ascii")).hexdigest(), digest)


def create_app(auth_mode="modal-proxy", digest=None, open_runtime=None):
    if auth_mode not in {"modal-proxy", "app-bearer"}:
        raise ValueError("Unknown authentication mode")
    if auth_mode == "app-bearer" and not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
        raise ValueError("An application token SHA-256 digest is required")

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, read=MAX_RESPONSE_SECONDS), trust_env=False, follow_redirects=False
        ) as client:
            app.state.client = client
            browser = mcp = None
            try:
                prepare_files()
                browser = start_unprivileged("/desktop-entrypoint", DESKTOP_UID, desktop_env(), BROWSER_STATE)
                await wait_ready(client, browser, f"{BROWSER}/healthz")
                mcp = start_unprivileged("/usr/local/bin/mcp-v8", MCP_UID, mcp_env(), MCP_STATE)
                await wait_ready(client, mcp, f"{MCP}/api/artifacts")
                yield
            finally:
                terminate(mcp)
                terminate(browser)

    async def mcp_endpoint(req: Request):
        if req.url.query or req.headers.get("origin"):
            return Response(status_code=400)
        if auth_mode == "app-bearer" and not bearer_digest_matches(req.headers.getlist("authorization"), digest):
            return Response(status_code=401, headers={"www-authenticate": "Bearer"})
        # Streamable HTTP permits no independent server-to-client GET stream.
        # POST responses can still be SSE, but are bounded to staging budgets.
        if req.method not in {"POST", "DELETE"}:
            return Response(status_code=405, headers={"allow": "POST, DELETE"})
        deadline = asyncio.get_running_loop().time() + MAX_RESPONSE_SECONDS
        body = bytearray()
        async for chunk in req.stream():
            body.extend(chunk)
            if len(body) > MAX_REQUEST_BYTES:
                return Response(status_code=413)
        client = req.app.state.client
        outgoing = httpx.Request(
            req.method, f"{MCP}/mcp",
            headers={key: value for key, value in req.headers.items() if key in REQUEST_HEADERS},
            content=bytes(body),
        )
        try:
            async with asyncio.timeout_at(deadline):
                upstream = await client.send(outgoing, stream=True)
        except (httpx.RequestError, TimeoutError):
            return JSONResponse({"error": "Desktop MCP unavailable"}, status_code=502)
        headers = {key: val for key, val in upstream.headers.items() if key in RESPONSE_HEADERS}

        async def chunks():
            try:
                async with asyncio.timeout_at(deadline):
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
            except (httpx.RequestError, TimeoutError):
                # Status was already sent. EOF makes the MCP client retry/report
                # an incomplete response rather than inventing a JSON-RPC result.
                return
            finally:
                await upstream.aclose()

        # Do not forward redirects or their destination to the client.
        if 300 <= upstream.status_code < 400:
            await upstream.aclose()
            return Response(status_code=502)
        return StreamingResponse(chunks(), status_code=upstream.status_code,
                                 headers=headers, background=BackgroundTask(upstream.aclose))

    app = Starlette(routes=[Route("/mcp", mcp_endpoint, methods=["GET", "POST", "DELETE"])],
                    lifespan=open_runtime or lifespan)
    app.router.redirect_slashes = False
    return app

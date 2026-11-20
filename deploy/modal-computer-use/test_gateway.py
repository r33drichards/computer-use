import hashlib
import os
import unittest
from unittest.mock import patch

import httpx

from gateway import MAX_REQUEST_BYTES, bearer_digest_matches, create_app
from runtime import BROWSER_CONFIG, DESKTOP_UID, EXEC_CONFIG, MCP_UID, UPSTREAMS, desktop_env, mcp_env, start_unprivileged

TOKEN = "a" * 64  # Public test fixture, not a credential.
DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.upstream_status = 200

        def upstream(req):
            self.calls.append(req)
            return httpx.Response(
                self.upstream_status,
                headers={"content-type": "text/event-stream",
                         "mcp-session-id": "mcp-fixture",
                         "set-cookie": "private=yes",
                         "location": "http://127.0.0.1/internal"},
                content=b"event: message\ndata: {}\n\n",
            )

        app = create_app("app-bearer", DIGEST)
        app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        self.addAsyncCleanup(app.state.client.aclose)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://example.test")
        self.addAsyncCleanup(self.client.aclose)
        self.auth = {"authorization": f"Bearer {TOKEN}"}

    async def test_supported_methods_and_sse(self):
        for method in ("POST", "DELETE"):
            result = await self.client.request(
                method, "/mcp", content=b"example", headers={
                    **self.auth, "accept": "text/event-stream",
                    "mcp-protocol-version": "2025-03-26", "mcp-session-id": "mcp-fixture",
                    "modal-key": "fixture", "modal-secret": "fixture", "cookie": "no",
                })
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.text, "event: message\ndata: {}\n\n")
            self.assertEqual(result.headers["mcp-session-id"], "mcp-fixture")
            self.assertNotIn("set-cookie", result.headers)
            self.assertNotIn("location", result.headers)
            request = self.calls[-1]
            self.assertEqual(str(request.url), "http://127.0.0.1:8080/mcp")
            self.assertEqual(request.headers["mcp-protocol-version"], "2025-03-26")
            self.assertEqual(request.content, b"example")
            for name in ("authorization", "modal-key", "modal-secret", "cookie"):
                self.assertNotIn(name, request.headers)

    async def test_fail_closed(self):
        for headers in ({}, {"authorization": "Bearer wrong"}, {
            **self.auth, "Authorization": f"Bearer {TOKEN}"  # Deliberate duplicate.
        }):
            self.assertEqual((await self.client.get("/mcp", headers=headers)).status_code, 401)
        self.assertEqual((await self.client.get("/mcp?token=no", headers=self.auth)).status_code, 400)
        self.assertEqual((await self.client.get("/mcp", headers={**self.auth, "origin": "https://other.test"})).status_code, 400)
        for path in ("/", "/mcp/", "/healthz", "/api/artifacts", "/vnc", "/exec"):
            self.assertEqual((await self.client.get(path, headers=self.auth)).status_code, 404)
        self.assertEqual((await self.client.get("/mcp", headers=self.auth)).status_code, 405)
        self.assertEqual((await self.client.head("/mcp", headers=self.auth)).status_code, 405)
        self.assertEqual((await self.client.post("/mcp", headers=self.auth, content=b"x" * (MAX_REQUEST_BYTES + 1))).status_code, 413)
        self.assertFalse(self.calls)

    async def test_blocks_redirects(self):
        self.upstream_status = 302
        result = await self.client.post("/mcp", headers=self.auth)
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("location", result.headers)


class RuntimeTests(unittest.TestCase):
    def test_digest_rejects_malformed_and_missing(self):
        self.assertTrue(bearer_digest_matches([f"Bearer {TOKEN}"], DIGEST))
        self.assertFalse(bearer_digest_matches([f"Basic {TOKEN}"], DIGEST))
        with self.assertRaises(ValueError):
            create_app("app-bearer", None)
        with self.assertRaises(ValueError):
            create_app("none")

    def test_secret_free_children(self):
        with patch.dict(os.environ, {"MODAL_TOKEN_SECRET": "BAD", "MCP_BEARER_SHA256": DIGEST}):
            self.assertNotIn("MODAL_TOKEN_SECRET", desktop_env())
            self.assertNotIn("MCP_BEARER_SHA256", mcp_env())
        self.assertNotEqual(MCP_UID, DESKTOP_UID)
        self.assertEqual(BROWSER_CONFIG["url"], "http://127.0.0.1:8081/mcp")
        self.assertEqual(mcp_env()["MCP_V8_BIND_HOST"], "127.0.0.1")
        self.assertEqual(EXEC_CONFIG, {"name": "exec", "transport": "http",
                                       "url": "http://127.0.0.1:8082/mcp"})
        self.assertEqual(UPSTREAMS, (BROWSER_CONFIG, EXEC_CONFIG))
        self.assertFalse(set(EXEC_CONFIG) & {"auth", "headers", "env"})
        with patch("runtime.subprocess.Popen") as spawn:
            start_unprivileged("/example", DESKTOP_UID, desktop_env(), "/tmp")
            self.assertEqual(spawn.call_args.kwargs["user"], DESKTOP_UID)
            self.assertEqual(spawn.call_args.kwargs["extra_groups"], [])

"""Read-only MCP discovery and a fresh-desktop screenshot smoke test."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

MAX_REPLY = 4 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def json_reply(stream, request_id):
    if stream.headers.get_content_type() == "text/event-stream":
        used = 0
        data = []
        while line := stream.readline(MAX_REPLY + 1):
            used += len(line)
            if used > MAX_REPLY:
                raise ValueError("SSE response too large")
            if line.startswith(b"data:"):
                data.append(line[5:].strip())
            elif not line.strip() and data:
                payload = b"\n".join(data)
                data.clear()
                # Streamable HTTP can prime the SSE stream with an empty
                # data field before returning a JSON-RPC response.
                if not payload.strip():
                    continue
                message = json.loads(payload)
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
        raise ValueError("No matching MCP reply in SSE response")
    body = stream.read(MAX_REPLY + 1)
    if len(body) > MAX_REPLY:
        raise ValueError("MCP response too large")
    return json.loads(body)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url")
    p.add_argument("--discovery-only", action="store_true")
    args = p.parse_args()
    url = urllib.parse.urlsplit(args.url)
    if url.scheme != "https" or url.username or url.password or not url.hostname or url.path != "/mcp" or url.query or url.fragment:
        p.error("Use an HTTPS URL ending in /mcp with no user info, query or fragment")
    opener = urllib.request.build_opener(NoRedirect)
    common = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    auth = {}
    if bearer := os.environ.get("COMPUTERUSE_APPLICATION_TOKEN"):
        auth["Authorization"] = "Bearer " + bearer
    if key := os.environ.get("COMPUTERUSE_MODAL_KEY"):
        secret = os.environ.get("COMPUTERUSE_MODAL_SECRET")
        if not secret:
            p.error("COMPUTERUSE_MODAL_SECRET is required with COMPUTERUSE_MODAL_KEY")
        auth.update({"Modal-Key": key, "Modal-Secret": secret})
    if not auth:
        p.error("Provide application bearer or dedicated Modal proxy credentials via environment")
    init = {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "modal-computer-use-smoke", "version": "0.1"}}
    identifier = 0
    session_headers = {}

    def post(method, params=None, *, authenticated=True, notification=False, destination=args.url):
        nonlocal identifier
        payload = {"jsonrpc": "2.0", "method": method}
        if not notification:
            identifier += 1
            payload["id"] = identifier
        if params is not None:
            payload["params"] = params
        request = urllib.request.Request(destination, method="POST", data=json.dumps(payload).encode(),
            headers={**common, **(auth if authenticated else {}), **session_headers})
        with opener.open(request, timeout=150) as reply:
            if notification:
                return reply.status, None, reply.headers
            return reply.status, json_reply(reply, identifier), reply.headers

    try:
        post("initialize", init, authenticated=False)
        raise ValueError("unauthenticated MCP initialize unexpectedly accepted")
    except urllib.error.HTTPError as error:
        if error.code not in (401, 403):
            raise ValueError(f"anonymous check expected 401/403; got HTTP {error.code}") from None
    missing = urllib.parse.urlunsplit((url.scheme, url.netloc, "/not-an-mcp-route", "", ""))
    try:
        post("initialize", init, destination=missing)
        raise ValueError("non-MCP route unexpectedly accepted")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise ValueError(f"non-MCP route expected 404; got HTTP {error.code}") from None
    _, message, headers = post("initialize", init)
    result = message.get("result", {})
    if not result.get("protocolVersion") or not isinstance(result.get("capabilities"), dict):
        raise ValueError("MCP initialize did not return a server protocol and capabilities")
    session_headers["MCP-Protocol-Version"] = result["protocolVersion"]
    if session := headers.get("Mcp-Session-Id"):
        session_headers["Mcp-Session-Id"] = session
    status, _, _ = post("notifications/initialized", notification=True)
    if status not in (200, 202, 204):
        raise ValueError(f"init notification got HTTP {status}")
    _, listing, _ = post("tools/list", {})
    tools = {tool.get("name") for tool in listing.get("result", {}).get("tools", [])}
    if "run_js" not in tools or "exec" in tools:
        raise ValueError("expected run_js without a directly exposed exec tool")
    print("PASS: authentication, route restriction, MCP initialize and tool listing")
    if args.discovery_only:
        return
    # A fixed local screenshot, never sent to this script or printed.
    code = """
const result = await mcp.callTool('browser', 'desktop_execute', {
  operations: [{ type: 'screen.grabRegion', params: {left: 0, top: 0, width: 16, height: 16} }],
});
if (result.isError || !result.content?.some(item => item.type === 'image' && item.data?.length)) {
  throw new Error('Desktop screenshot did not return image content');
}
console.log('COMPUTERUSE_DESKTOP_SMOKE_OK');
"""
    _, result, _ = post("tools/call", {"name": "run_js", "arguments": {"code": code, "execution_timeout_secs": 20}})
    inner = result.get("result", {})
    if inner.get("isError") or "COMPUTERUSE_DESKTOP_SMOKE_OK" not in json.dumps(inner):
        raise ValueError("run_js did not confirm desktop screenshot")
    _, reply, _ = post("tools/list", {})
    if "run_js" not in {tool.get("name") for tool in reply.get("result", {}).get("tools", [])}:
        raise ValueError("MCP session no longer returned the expected tools after the screenshot")
    print("PASS: run_js captured a 16×16 image and MCP session remained usable")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        sys.exit(f"FAIL: HTTP {error.code}")
    except (ValueError, OSError, TimeoutError) as error:
        sys.exit(f"FAIL: {type(error).__name__}: {error}")

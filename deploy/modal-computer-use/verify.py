"""Private one-shot verification of exact Dockerfile + MCP gateway."""
import hashlib
import json

import httpx
from gateway import create_app

TOKEN = "0123456789abcdef" * 4  # Only this unexposed test app; not a credential.
MARKER = "COMPUTERUSE_DESKTOP_SMOKE_OK"
SCREEN_TEST = f"""
const nested = mcp.listTools();
if (mcp.servers.includes('exec') || nested.some(tool => tool.server === 'exec')) {{
  throw new Error('Unexpected shell MCP upstream');
}}
if (!nested.some(tool => tool.server === 'browser' && tool.name === 'desktop_execute')) {{
  throw new Error('Desktop tool is missing');
}}
const response = await mcp.callTool('browser', 'desktop_execute', {{
  operations: [{{ type: 'screen.grabRegion', params: {{left: 0, top: 0, width: 16, height: 16}} }}],
}});
if (response.isError || !response.content?.some(x => x.type === 'image' && x.data?.length)) {{
  throw new Error('No desktop PNG');
}}
console.log('{MARKER}');
"""


def message(response, identifier):
    if "text/event-stream" in response.headers.get("content-type", ""):
        for event in response.text.replace("\r\n", "\n").split("\n\n"):
            payload = "\n".join(line[5:].lstrip() for line in event.splitlines()
                                if line.startswith("data:"))
            if payload:
                obj = json.loads(payload)
                if obj.get("id") == identifier:
                    return obj
        raise ValueError(f"No matching SSE reply for request {identifier}")
    obj = response.json()
    if obj.get("id") != identifier:
        raise ValueError(f"Unexpected reply for request {identifier}")
    return obj


async def verify():
    api = create_app("app-bearer", hashlib.sha256(TOKEN.encode("ascii")).hexdigest())
    async with api.router.lifespan_context(api):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url="https://private-test.invalid"
        ) as client:
            headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}
            initialize = {"protocolVersion": "2025-03-26", "capabilities": {},
                          "clientInfo": {"name": "private-image-smoke", "version": "0.1"}}
            _init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": initialize}
            if (await client.post("/mcp", json=_init)).status_code != 401:
                raise ValueError("Uncredentialed MCP accepted")
            if (await client.post("/vnc", json=_init, headers=headers)).status_code != 404:
                raise ValueError("Unexpected public route accepted")

            async def post(identifier, method, params=None):
                data = {"jsonrpc": "2.0", "method": method}
                if identifier is not None:
                    data["id"] = identifier
                if params is not None:
                    data["params"] = params
                response = await client.post("/mcp", json=data, headers=headers)
                response.raise_for_status()
                if identifier is None:
                    return {}, response.headers
                obj = message(response, identifier)
                if "result" not in obj:
                    raise ValueError(f"JSON-RPC error on {method}")
                return obj["result"], response.headers

            initialized, response_headers = await post(1, "initialize", initialize)
            headers["MCP-Protocol-Version"] = initialized["protocolVersion"]
            if sid := response_headers.get("mcp-session-id"):
                headers["MCP-Session-Id"] = sid
            await post(None, "notifications/initialized")
            tools, _ = await post(2, "tools/list", {})
            names = {tool["name"] for tool in tools["tools"]}
            if "run_js" not in names or "exec" in names:
                raise ValueError("Expected run_js without direct shell tool")
            result, _ = await post(3, "tools/call", {"name": "run_js", "arguments": {
                "code": SCREEN_TEST, "execution_timeout_secs": 20,
            }})
            if result.get("isError") or MARKER not in json.dumps(result):
                raise ValueError("run_js did not confirm a synthetic screen grab")
            print("PASS: loopback MCP authenticated, listed tools and executed desktop screenshot")
            return "desktop MCP ready"

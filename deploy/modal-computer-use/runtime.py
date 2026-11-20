"""Isolated desktop and upstream MCP lifecycle. No deployment side effects."""
import asyncio
import json
import os
import signal
import subprocess
import time

import httpx

DESKTOP_UID = 1000
MCP_UID = 1001
BROWSER = "http://127.0.0.1:8081"
MCP = "http://127.0.0.1:8080"
BROWSER_STATE = "/var/lib/modal-desktop"
MCP_STATE = "/var/lib/modal-mcp"
CONFIG = f"{MCP_STATE}/servers.json"
BROWSER_CONFIG = {"name": "browser", "transport": "http", "url": f"{BROWSER}/mcp"}
POLICY = {
    "mcp_tools": {"policies": [{"url": "file:///etc/mcp/wrapper-tools.rego"}]},
    "filesystem": {"policies": [{"url": "file:///etc/mcp/wrapper-filesystem.rego"}]},
    "fetch": {"policies": [{"url": "file:///etc/mcp/wrapper-fetch.rego"}]},
}
BASE_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}


def desktop_env():
    return dict(BASE_ENV, HOME="/home/desktop", SESSION_MODE="1", DATA_DIR=BROWSER_STATE)


def mcp_env():
    return dict(
        BASE_ENV,
        HOME=MCP_STATE,
        MCP_V8_BIND_HOST="127.0.0.1",
        MCP_V8_HTTP_PORT="8080",
        MCP_V8_ALLOWED_HOSTS="127.0.0.1",
        MCP_V8_HEAP_STORE="none",
        MCP_V8_MCP_CONFIG=CONFIG,
        MCP_V8_SESSION_DB_PATH=f"{MCP_STATE}/sessions",
        MCP_V8_POLICIES_JSON=json.dumps(POLICY),
    )


def start_unprivileged(executable, uid, env, cwd):
    return subprocess.Popen(
        [executable], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        user=uid, group=uid, extra_groups=[], start_new_session=True,
    )


async def wait_ready(client, process, url, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Upstream process exited with status {process.returncode}")
        try:
            if (await client.get(url)).status_code == 200:
                return
        except httpx.RequestError:
            pass
        await asyncio.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for internal endpoint {url}")


def terminate(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        # Terminate leftover X/browser processes even if the group leader exited.
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2)


def prepare_files():
    # Only the outer service can modify its policy; no separate exec MCP exists.
    policy_dir = "/etc/mcp"
    policy_files = {
        "wrapper-tools.rego": '''package mcp.tools
default allow := false
allow if {
    input.server == "browser"
    input.tool in {"browser_execute", "desktop_execute"}
}
''',
        "wrapper-filesystem.rego": '''package mcp.filesystem
default allow := false
''',
        "wrapper-fetch.rego": '''package mcp.fetch
default allow := false
''',
    }
    for name, text in policy_files.items():
        fd = os.open(os.path.join(policy_dir, name), os.O_NOFOLLOW | os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w") as file:
            file.write(text)
    fd = os.open(CONFIG, os.O_NOFOLLOW | os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        os.fchown(file.fileno(), MCP_UID, MCP_UID)
        json.dump([BROWSER_CONFIG], file)

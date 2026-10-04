#!/usr/bin/env python3
"""Git credential protocol adapter for the session-only Computer Use broker."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "get":
        return 0  # Never store GitHub credentials on disk.
    fields = {}
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            break
        key, sep, value = line.partition("=")
        if sep:
            fields[key] = value
    if fields.get("protocol") != "https" or fields.get("host") != "github.com":
        return 0
    broker = os.environ.get("CU_GITHUB_BROKER_URL", "")
    credential = os.environ.get("CU_GITHUB_CREDENTIAL", "")
    session = os.environ.get("CU_GITHUB_SESSION", "")
    if not broker or not credential or not session:
        return 0
    parsed = urllib.parse.urlsplit(broker)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        print("Computer Use: invalid GitHub broker configuration", file=sys.stderr)
        return 1
    request = urllib.request.Request(
        broker.rstrip("/") + "/internal/github/credentials",
        data=json.dumps({"session": session, "protocol": "https", "host": "github.com"}).encode(),
        headers={"Authorization": "Bearer " + credential, "Content-Type": "application/json"},
        method="POST",
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    # A user-set HTTP proxy must never receive the session credential.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            result = json.loads(response.read(65536))
        username, password = result["username"], result["password"]
        if not all(isinstance(v, str) and v and not any(c in v for c in "\r\n\0") for v in (username, password)):
            raise ValueError("invalid credentials")
    except (urllib.error.URLError, ValueError, KeyError, TimeoutError):
        print("Computer Use: GitHub authentication unavailable. Check account connections or create a new session after reconnecting.", file=sys.stderr)
        return 1
    print("username=" + username)
    print("password=" + password)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

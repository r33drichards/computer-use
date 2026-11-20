# Computer Use MCP on Modal

Builds the public Computer Use browser desktop source at
`63bab526d2a999af969657f70a342dfebe1cbb63` and the project's pinned mcp-js
source at `453c6b29e4797efa204e417c2baf966fec6bc4ff`. It doesn't need access to
the existing private Artifact Registry. The upstream browser's Nix lock and the
MCP Cargo lock are used. The published OCI artifact is imported by digest.

This is **a fresh Linux desktop**, not a copy of the GKE desktop, Chrome profile,
session ID, login state, GitHub credentials, or files. It does not connect to your
Mac. The browser and MCP processes run as different unprivileged UIDs with
separate working directories and only explicit environment variables. No disk
volume is attached. Idle scale-down and redeploy erase the desktop. Only the
MCP path is exposed, with one worker; the browser MCP, desktop exec MCP and
runtime listen on loopback, and noVNC is not started. Only the authenticated
gateway reaches the desktop's exec tools via the existing MCP-JS wrapper.
Commands run as the unprivileged desktop user, not the gateway or MCP-JS user.
There is no command allowlist. The direct JS filesystem, subprocess and fetch
policies still deny by default. Do not attach private mounts, credentials, or
broad infrastructure access. This is not an egress policy or a replacement for
the full GKE setup.

## Build, smoke-test and publish

The [image workflow](../../.github/workflows/modal-computer-use-image.yml) builds
for linux/amd64 on a GitHub-hosted runner. It runs MCP discovery and an unprivileged desktop exec check and a synthetic
16×16 desktop screenshot in the **built image**, with no external network or
published port, and publishes that exact image only on a trusted repository
push. Published tags identify source commit and CI run, and the job summary
lists the immutable OCI digest.

GHCR can default a new package to private. On the
[package page](https://github.com/users/r33drichards/packages/container/package/computer-use-modal),
an authorized package admin can use
[package visibility settings](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)
to make it public. The public image contains only source-built software and
fixtures, never user desktop state, gateway secrets, or a deployment endpoint.
Use a fresh Docker config to verify anonymous pull before trusting the digest:

```sh
# Replace the placeholder with the verified CI summary entry.
export COMPUTER_USE_IMAGE=ghcr.io/r33drichards/computer-use-modal@sha256:<digest>
DOCKER_CONFIG="$(mktemp -d)" docker pull --platform linux/amd64 "$COMPUTER_USE_IMAGE"
```

## Validate without deploying

```sh
python -m pip install -r requirements-runtime.txt
python -m unittest -v
python -m compileall -q .
```

The unit tests mock the localhost service; they do not prove the image builds,
Chromium/Xvnc starts on Modal, or an external MCP client can reconnect. The runtime's original
artifact endpoints are not exposed by the gateway. This intentionally supports
short MCP exchanges only: POST responses can stream with a deadline, while
independent GET streams return 405 so an idle client cannot keep the worker
running. Test this with the actual MCP client before changing its config.

If authorized to use Modal build resources, run the one-shot private image test
with `COMPUTER_USE_IMAGE="$COMPUTER_USE_IMAGE" modal run verify_app.py::verify_image`. This is a separate ephemeral App
that has no web function, secret, deployment, volume, or public URL. It starts
the real services from the already-built image, checks authorization and MCP discovery through the
loopback ASGI gateway, calls a 16×16 synthetic screenshot, and stops both
children. It uses no existing desktop data.

## Staging authentication

- Default `modal-proxy` requests Modal proxy authentication. **Do not share a
  workspace-wide proxy token with an MCP client.** Use a suitable scoped environment
  only after checking the token's granted scope.
- Optional `app-bearer` uses a separate application bearer for only this MCP
  route. The named Modal Secret contains **only** the lowercase SHA-256 digest
  of a random 32-byte hex bearer as `MCP_BEARER_SHA256`; the bearer remains
  in the caller's approved credential store. Do not use a human password.
  The gateway refuses startup if the digest is absent or malformed, validates
  the request and strips all auth headers before forwarding. This creates a
  public URL but not unauthenticated tool access; do not use this mode if the
  Modal environment blocks publicly reachable endpoints.

Before live deployment, use an approved staging environment and review billing
and token scope. If authorized, `modal deploy app.py` with the verified `COMPUTER_USE_IMAGE`
and an intentional `COMPUTER_USE_AUTH_MODE` imports the built image and deploys. Don’t switch existing clients until the new endpoint is verified. Verify unauthenticated denial, MCP initialize/tools/list, a small
`run_js` call and a synthetic desktop screenshot in the newly deployed Linux
desktop. Then check that a second request on the same MCP session works and the
worker scales down. A running desktop snapshot from GKE cannot be restored here.

`COMPUTER_USE_DEV_DOCKERFILE=1` opens the experimental source-build path for
developers only. It is not the recommended Modal staging path.

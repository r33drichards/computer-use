"""Modal app declaration. Importing does not deploy the app or start a desktop."""
import os

import modal
from image_spec import image
MODE = os.environ.get("COMPUTER_USE_AUTH_MODE", "modal-proxy")
if MODE not in {"modal-proxy", "app-bearer"}:
    raise ValueError("COMPUTER_USE_AUTH_MODE must be modal-proxy or app-bearer")

# The scoped option stores only a digest, never the bearer itself. No secrets
# are attached in default mode; neither child inherits Modal's environment.
secrets = [modal.Secret.from_name("computer-use-mcp-bearer-digest")] if MODE == "app-bearer" else []
app = modal.App("isolated-computer-use-mcp")
@app.function(image=image, secrets=secrets, cpu=1.5, memory=3072,
              min_containers=0, max_containers=1, scaledown_window=120,
              timeout=300)
@modal.concurrent(max_inputs=8)
@modal.asgi_app(requires_proxy_auth=MODE == "modal-proxy")
def web():
    from gateway import create_app
    return create_app(MODE, os.environ.get("MCP_BEARER_SHA256"))

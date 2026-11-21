"""Opt-in disk-only backend for the existing production app ID and MCP URL."""
import os
from contextlib import asynccontextmanager

import modal
from image_spec import MODE, reference

if MODE != "app-bearer" or not reference:
    raise ValueError("Persistent desktop requires the existing owner bearer boundary and a pinned release")
TEST = os.environ.get("COMPUTER_USE_CHECKPOINT_TEST") == "1"
APP = "private-hermes-checkpoint-gateway-canary" if TEST else "isolated-computer-use-mcp"
app = modal.App(APP)
base = modal.Image.from_registry(reference)
controller_image = base.env({"COMPUTER_USE_IMAGE": reference, "COMPUTER_USE_AUTH_MODE": MODE, "COMPUTER_USE_CHECKPOINT_TEST": "1" if TEST else "0"}).add_local_python_source("image_spec", "persistent", "checkpoint_gateway", "checkpoint_verify")
state = modal.Dict.from_name("hermes-checkpoint-gateway-canary-v2" if TEST else "hermes-desktop-checkpoint-v1", create_if_missing=True)
owner_digest = modal.Secret.from_name("computer-use-mcp-bearer-digest")


@app.cls(image=controller_image, min_containers=0, max_containers=1, scaledown_window=120, timeout=300)
class OwnerDesktop:
    @modal.enter()
    def configure(self):
        from persistent import Controller
        self.controller = Controller(APP, app, base, state, idle=0 if TEST else 900, block_network=TEST)

    @modal.method(is_generator=True)
    async def stream(self, method, headers, body):
        async for f in self.controller.exchange(method, headers, body):
            yield f

    @modal.method()
    async def idle_checkpoint(self):
        return await self.controller.checkpoint_if_idle()


@asynccontextmanager
async def controller_gateway(_app):
    yield


if TEST:
    @app.function(image=controller_image, timeout=300)
    async def verify():
        from checkpoint_verify import run
        return await run(OwnerDesktop(), controller_gateway)
else:
    @app.function(image=controller_image, schedule=modal.Period(minutes=5), timeout=120)
    def checkpoint_idle_owner_desktop():
        return OwnerDesktop().idle_checkpoint.remote()

    @app.function(image=controller_image, secrets=[owner_digest], cpu=1.5, memory=3072,
                  min_containers=0, max_containers=1, scaledown_window=120, timeout=300)
    @modal.concurrent(max_inputs=8)
    @modal.asgi_app()
    def web():
        from checkpoint_gateway import create_app
        return create_app("app-bearer", os.environ.get("MCP_BEARER_SHA256"),
                          open_runtime=controller_gateway, exchange=OwnerDesktop().stream.remote_gen.aio)

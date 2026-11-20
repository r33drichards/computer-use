"""Select exactly the image that was built and runtime-tested by image CI."""
import os
import re
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent
PUBLISHED_IMAGE = re.compile(r"ghcr\.io/r33drichards/computer-use-modal@sha256:[a-f0-9]{64}")
reference = os.environ.get("COMPUTER_USE_IMAGE")
if reference:
    if not PUBLISHED_IMAGE.fullmatch(reference):
        raise ValueError("COMPUTER_USE_IMAGE must be the canonical GHCR package with an immutable sha256 digest")
    image = modal.Image.from_registry(reference)
    image = image.env({"COMPUTER_USE_IMAGE": reference})
elif os.environ.get("COMPUTER_USE_DEV_DOCKERFILE") == "1":
    # Build-only experiments; normal staging uses an audited CI image digest.
    image = modal.Image.from_dockerfile(ROOT / "Dockerfile", context_dir=ROOT).env({"COMPUTER_USE_DEV_DOCKERFILE": "1"})
else:
    raise ValueError("Set COMPUTER_USE_IMAGE to the verified digest from CI")

# Modal mounts the function entry module but not its sibling import by default.
# Runtime code remains in the digest-pinned registry image, exactly as tested by CI.
image = image.add_local_python_source("image_spec")

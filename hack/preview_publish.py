#!/usr/bin/env python3
"""Publish Docker archives without executing their contents or PR code."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

import preview

REGISTRY = "us-west1-docker.pkg.dev/browserjs-sessions/browserjs-previews"


def target_image(name, pr, sha, registry):
    if name not in preview.IMAGES or registry != REGISTRY or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid preview registry, image name or SHA")
    return f"{registry}/{name}:pr-{preview.pr_number(pr)}-{sha}"


def command(*args):
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--pr", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = target_image(args.name, args.pr, args.sha, os.environ["PREVIEW_REGISTRY"])
    if args.archive.is_symlink() or not args.archive.is_file():
        raise ValueError("Expected a regular Docker archive")
    command("docker", "load", "--input", str(args.archive))
    source = f"preview/{args.name}:build"
    command("docker", "image", "inspect", source)
    command("docker", "tag", source, target)
    command("gcloud", "auth", "configure-docker", REGISTRY.split("/")[0], "--quiet")
    command("docker", "push", target)
    metadata = json.loads(command("docker", "image", "inspect", target))[0]
    repository = f"{REGISTRY}/{args.name}"
    image = next(d for d in metadata["RepoDigests"] if d.startswith(repository + "@sha256:"))
    preview.validate_images({name: image if name == args.name else f"{REGISTRY}/{name}@sha256:" + "0" * 64 for name in preview.IMAGES})
    args.output.write_text(json.dumps({"pr": preview.pr_number(args.pr), "sha": args.sha, "name": args.name, "image": image}))
    print(f"Published {image}")


if __name__ == "__main__":
    main()

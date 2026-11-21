#!/usr/bin/env bash
# Called by both read-only pull request CI and the trusted publication job.
set -euo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^computer-use-modal-ci:[a-z0-9-]+$ ]]; then
  echo 'usage: ci-build.sh computer-use-modal-ci:<local-tag>' >&2
  exit 2
fi
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
image=$1

docker buildx build --platform linux/amd64 --load --tag "$image" \
  --file "$here/Dockerfile" --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" "$here"
test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")" = linux/amd64

# The exact local image that would be published must pass. No host port,
# external network, credentials or privileged container is used.
timeout 5m docker run --rm --network none --shm-size 256m \
  --security-opt no-new-privileges --entrypoint python "$image" \
  -c 'import asyncio, verify; assert asyncio.run(verify.verify()) == "desktop MCP ready"'

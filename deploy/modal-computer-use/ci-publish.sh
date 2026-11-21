#!/usr/bin/env bash
# Only called by a trusted push job after the same local image passes smoke.
set -euo pipefail

[[ "${GITHUB_EVENT_NAME:?}" == push ]]
[[ "${GITHUB_REPOSITORY:?}" == r33drichards/computer-use ]]
case "${GITHUB_REF:?}" in
  refs/heads/main|refs/heads/codex/modal-computer-use) ;;
  *) echo 'Ref is not permitted to publish' >&2; exit 2 ;;
esac
[[ "${GITHUB_SHA:?}" =~ ^[a-f0-9]{40}$ ]]
[[ "${GITHUB_RUN_ID:?}" =~ ^[0-9]+$ && "${GITHUB_RUN_ATTEMPT:?}" =~ ^[0-9]+$ ]]
[[ $# -eq 1 && "$1" =~ ^computer-use-modal-ci:[a-z0-9-]+$ ]]
[[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1") == "$GITHUB_SHA" ]]

package=ghcr.io/r33drichards/computer-use-modal
tag="sha-$GITHUB_SHA-run-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
push_log=$(mktemp)
trap 'rm -f "$push_log"' EXIT

docker tag "$1" "$package:$tag"
docker push "$package:$tag" | tee "$push_log"
digest=$(sed -nE 's/^.*digest: (sha256:[0-9a-f]{64}) size: [0-9]+.*$/\1/p' "$push_log")
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]
docker buildx imagetools inspect "$package@$digest" >/dev/null
{
  echo "### Tested linux/amd64 image"
  printf '\nTag: \`%s\`\n\nPinned reference: \`%s\`\n' "$package:$tag" "$package@$digest"
  printf '\nUse an anonymous pull to confirm package visibility before Modal import.\n'
} >> "$GITHUB_STEP_SUMMARY"

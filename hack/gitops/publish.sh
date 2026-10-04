#!/usr/bin/env bash
# Commit an immutable release to the branch Argo CD watches. No cluster apply.
set -euo pipefail
source_commit="${1:?source commit}"
artifacts="${2:?build artifacts directory}"
[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || exit 1
work="$(mktemp -d)"
trap 'git worktree remove --force "$work/tree" 2>/dev/null || true; rm -rf "$work"' EXIT
# Do not deploy a commit superseded while its images or tests were building.
latest="$(gh api "repos/$GITHUB_REPOSITORY/commits/main" --jq .sha)"
if [ "$latest" != "$source_commit" ]; then
  echo 'A newer main exists: this release is superseded.'
  echo 'skipped=true' >> "$GITHUB_OUTPUT"
  exit 0
fi
git fetch --quiet origin production
git worktree add --quiet --detach "$work/tree" FETCH_HEAD
previous="$(git -C "$work/tree" rev-parse HEAD)"
python3 hack/gitops/render.py --source "$source_commit" \
  --previous "$work/tree/production/release.json" --artifacts "$artifacts" --output "$work/rendered"
cp "$work/rendered/"* "$work/tree/production/"
git -C "$work/tree" config user.name 'github-actions[bot]'
git -C "$work/tree" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$work/tree" add production
git -C "$work/tree" commit -m "Deploy $source_commit"
revision="$(git -C "$work/tree" rev-parse HEAD)"
# A normal push refuses a concurrent production update.
git -C "$work/tree" push origin HEAD:refs/heads/production
printf 'previous=%s\nrevision=%s\n' "$previous" "$revision" >> "$GITHUB_OUTPUT"

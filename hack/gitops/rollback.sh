#!/usr/bin/env bash
# Roll Git's desired state back with a forward commit, preserving history.
set -euo pipefail
failed="${1:?failed revision}" previous="${2:?previous revision}"
[[ "$failed" =~ ^[0-9a-f]{40}$ && "$previous" =~ ^[0-9a-f]{40}$ ]] || exit 1
branch="${GITOPS_BRANCH:-production}"
app="${ARGOCD_APP:-computer-use-production}"
work="$(mktemp -d)"
trap 'git worktree remove --force "$work/tree" 2>/dev/null || true; rm -rf "$work"' EXIT
git fetch --quiet origin "$branch"
git worktree add --quiet --detach "$work/tree" FETCH_HEAD
[ "$(git -C "$work/tree" rev-parse HEAD)" = "$failed" ] || { echo 'Production changed: refusing to overwrite another release.' >&2; exit 1; }
git -C "$work/tree" checkout "$previous" -- production
git -C "$work/tree" config user.name 'github-actions[bot]'
git -C "$work/tree" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$work/tree" commit -m "Roll back failed release $failed"
git -C "$work/tree" push origin "HEAD:refs/heads/$branch"
revision="$(git -C "$work/tree" rev-parse HEAD)"
kubectl -n argocd annotate application "$app" argocd.argoproj.io/refresh=hard --overwrite
python3 hack/gitops/wait.py "$revision" 1200

#!/usr/bin/env bash
# Read-only identity receipt for the tree actually used by local-context builds.
set -euo pipefail
: "${EXPECTED_SOURCE:?immutable expected source SHA required}"
[[ "$EXPECTED_SOURCE" =~ ^[0-9a-f]{40}$ ]] || { echo 'invalid expected source SHA' >&2; exit 1; }
actual="$(git rev-parse HEAD)"
[ "$actual" = "$EXPECTED_SOURCE" ] || { echo 'checkout does not match expected source SHA' >&2; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo 'tracked source tree is dirty' >&2; exit 1; }
tree="$(git rev-parse 'HEAD^{tree}')"
parents="$(git show -s --format=%P HEAD)"
printf 'tested source sha=%s tree=%s parents=%s\n' "$actual" "$tree" "$parents"
if [ -n "${GITHUB_OUTPUT:-}" ]; then printf 'sha=%s\ntree=%s\n' "$actual" "$tree" >> "$GITHUB_OUTPUT"; fi
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then printf 'Tested source: commit %s, tree %s, parents %s.\n' "$actual" "$tree" "$parents" >> "$GITHUB_STEP_SUMMARY"; fi

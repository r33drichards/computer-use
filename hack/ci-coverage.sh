#!/usr/bin/env bash
# Fails when a component of the repo has no workflow that mentions it, so a new
# Go module, crate, npm package, TLA+ spec or Python package cannot be added
# without CI for it. See docs/ci-notes.md.
set -euo pipefail
cd "$(dirname "$0")/.."

# Directories that need no check of their own, with the reason.
skip=(
  "sdk/js"      # covered by sdk.yml through sdk/**
  "sdk/python"  # covered by sdk.yml through sdk/**
)

mentioned() { grep -rqF -- "$1" .github/workflows; }

missing=0
while IFS= read -r dir; do
  dir=${dir#./}
  [ "$dir" = . ] && continue
  for s in "${skip[@]}"; do [ "$dir" = "$s" ] && continue 2; done
  # a workflow naming the directory or a parent of it counts
  p=$dir
  found=0
  while [ "$p" != . ]; do
    if mentioned "$p/" || mentioned "working-directory: $p" ; then found=1; break; fi
    p=$(dirname "$p")
  done
  if [ $found = 0 ]; then echo "no workflow mentions $dir"; missing=1; fi
done < <(git ls-files -- '*/go.mod' '*/Cargo.toml' '*/package.json' '*/pyproject.toml' '*.tla' | xargs -n1 dirname | sort -u | sed 's|^|./|')
exit $missing

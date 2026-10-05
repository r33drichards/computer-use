#!/usr/bin/env bash
# Fails when a component of the repo has no workflow that runs or watches it,
# so a new Go module, crate, npm package, TLA+ spec or Python package cannot
# be added without CI for it. See docs/ci-notes.md.
#
# A component directory D counts as covered when a workflow has, for D or a
# parent of it (the root is covered only through its own manifest file):
#   - a `paths:` entry starting with D/ (or naming the manifest, for the root),
#   - `working-directory: D`, or
#   - `cd D`.
# Comments and negated (`!`) path entries do not count. It is a guard against
# forgetting, not a proof that the workflow runs the right thing.
#
# ROOT overrides the repository to check (for the tests).
set -euo pipefail
cd "${ROOT:-$(dirname "$0")/..}"

# Directories that need no check of their own, with the reason.
skip=(
  "sdk/js"      # covered by sdk.yml through sdk/**
  "sdk/python"  # covered by sdk.yml through sdk/**
)

workflows=$(find .github/workflows -name '*.yml' 2>/dev/null)
mentioned() { # $1: an extended regex
  # shellcheck disable=SC2086
  [ -n "$workflows" ] && grep -hE -- "$1" $workflows | grep -vE '^\s*#' | grep -q .
}
esc() { printf '%s' "$1" | sed -E 's/[][\.*^$+?(){}|/]/\\&/g'; }

missing=0
while IFS= read -r file; do
  dir=$(dirname "$file")
  case $file in
    *.tla) # specs are run by hack/tlc-check.sh, which covers every spec/*/
      if mentioned 'tlc-check\.sh'; then continue; fi
      echo "no workflow runs hack/tlc-check.sh for $file"; missing=1; continue ;;
  esac
  for s in "${skip[@]}"; do [ "$dir" = "$s" ] && continue 2; done
  if [ "$dir" = . ]; then
    # a root manifest is covered by a workflow that lists it in `paths:`
    if mentioned "^\s*-\s*['\"]?$(esc "$file")['\"]?\s*$"; then continue; fi
    echo "no workflow lists the root file $file under paths:"; missing=1; continue
  fi
  p=$dir
  found=0
  while [ "$p" != . ]; do
    e=$(esc "$p")
    if mentioned "^\s*-\s*['\"]?$e/" || mentioned "working-directory:\s*['\"]?$e(['\"]|\s|$)" || mentioned "\bcd\s+$e(\s|/|$)"; then found=1; break; fi
    p=$(dirname "$p")
  done
  if [ $found = 0 ]; then echo "no workflow runs or watches $dir"; missing=1; fi
done < <(git ls-files -- 'go.mod' '*/go.mod' 'Cargo.toml' '*/Cargo.toml' 'package.json' '*/package.json' 'pyproject.toml' '*/pyproject.toml' '*.tla' | sort -u)
exit $missing

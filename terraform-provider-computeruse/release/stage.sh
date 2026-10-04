#!/usr/bin/env bash
set -euo pipefail
sha="${1:?usage: stage.sh FULL_SOURCE_SHA [--preparation]}"
mode="${2:-final}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "full immutable source SHA required" >&2; exit 1; }
[[ "$mode" == final || "$mode" == --preparation ]] || exit 1
lane="$(cd "$(dirname "$0")/../.." && pwd)"
release="$lane/terraform-provider-computeruse/release"
[[ "$(git -C "$lane" cat-file -t "$sha")" == commit && "$(git -C "$lane" rev-parse "$sha^{commit}")" == "$sha" ]] || { echo "source commit identity mismatch" >&2; exit 1; }
if [[ "$mode" == final ]]; then
 git -C "$lane" cat-file -e "$sha:terraform-provider-computeruse/release/copy.bara.sky" 2>/dev/null || { echo "committed release inputs required" >&2; exit 1; }
 git -C "$lane" diff --quiet "$sha" -- terraform-provider-computeruse sdk LICENSE THIRD_PARTY.md docs/contracts/policy docs/terraform-provider.md || { echo "dirty source mismatch" >&2; exit 1; }
 [[ -z "$(git -C "$lane" ls-files --others --exclude-standard terraform-provider-computeruse/release)" ]] || { echo "uncommitted release overlay refused" >&2; exit 1; }
fi
: "${COPYBARA:?official COPYBARA executable required}"
work="${RELEASE_WORK:-$(dirname "$lane")/artifacts/export-$sha}"
[[ ! -e "$work" ]] || { echo "refusing existing export directory" >&2; exit 1; }
mkdir -p "$work/source" "$work/home" "$work/tmp"
git -C "$lane" archive "$sha" | tar -x -C "$work/source"
template="$work/source/terraform-provider-computeruse/release/copy.bara.sky"
[[ "$mode" != --preparation ]] || template="$release/copy.bara.sky"
python3 - "$template" "$work/copy.bara.sky" "$sha" <<'PY'
import sys
from pathlib import Path
s=Path(sys.argv[1]).read_text()
assert s.count('@@SOURCE_SHA@@') == 1
Path(sys.argv[2]).write_text(s.replace('@@SOURCE_SHA@@',sys.argv[3]))
PY
export HOME="$work/home" TMPDIR="$work/tmp" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
"$COPYBARA" validate "$work/copy.bara.sky" provider_local
"$COPYBARA" migrate --folder-dir="$work/mirror" --output-root="$work/copybara" "$work/copy.bara.sky" provider_local "$sha"
mkdir -p "$work/mirror/release"
printf '%s
' "$sha" > "$work/mirror/release/SOURCE_SHA"
if [[ "$mode" == final ]]; then
 mkdir -p "$work/mirror/.github/workflows"
 cp "$work/source/terraform-provider-computeruse/release/provider-release.yml" "$work/mirror/.github/workflows/provider-release.yml"
 checker="$work/source/terraform-provider-computeruse/release/check-mirror.py"
else
 printf '%s
' 'PREPARATION ONLY: no local release overlay copied' > "$work/PREPARATION_ONLY"
 checker="$release/check-mirror.py"
fi
python3 "$checker" "$work/mirror" "$work/source"

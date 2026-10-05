#!/usr/bin/env bash
# The failing configurations are regression checks: failure is expected.
set -euo pipefail
cd "$(dirname "$0")"
tlc_bin="${TLC:-tlc}"
if ! command -v "$tlc_bin" >/dev/null 2>&1; then
  exec nix shell nixpkgs#tlaplus -c bash ./check.sh
fi
state_dir="$(mktemp -d "${TMPDIR:-/tmp}/session-snapshot.XXXXXX")"
trap 'rm -rf "$state_dir"' EXIT
mkdir -p traces
for config in current missing-file database-hypothesis quiesced uncoordinated-pair paired; do
  status=0
  "$tlc_bin" -cleanup -workers 1 -metadir "$state_dir/$config" \
    -config "$config.cfg" SessionSnapshot.tla > "traces/$config.txt" 2>&1 || status=$?
  case "$config" in
    current|uncoordinated-pair) invariant=RestoreUsesCompatibleDisk ;;
    missing-file) invariant=NoMissingChromeFile ;;
    database-hypothesis) invariant=NoDatabaseCorruption ;;
    quiesced|paired) invariant= ;;
  esac
  if [[ "$config" = quiesced || "$config" = paired ]]; then
    if [[ "$status" != 0 ]] || ! rg -q 'Model checking completed. No error has been found.' "traces/$config.txt"; then
      cat "traces/$config.txt"
      exit 1
    fi
    printf '%s: all invariants hold\n' "$config"
  else
    if [[ "$status" != 12 ]] || ! rg -q "Invariant $invariant is violated" "traces/$config.txt"; then
      cat "traces/$config.txt"
      exit 1
    fi
    printf '%s: reproduced %s violation\n' "$config" "$invariant"
  fi
  rg 'states generated|depth of the complete' "traces/$config.txt"
done

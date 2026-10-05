#!/usr/bin/env bash
# Model-checks every TLA+ spec under spec/. A spec directory's configurations
# are named for their result: a configuration listed in its `expect-violation`
# file must make TLC find an invariant violation (they pin down what the model
# says is broken today); every other .cfg must hold.
#
# Needs TLA2TOOLS to point at tla2tools.jar, and java.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TLA2TOOLS:?set TLA2TOOLS to tla2tools.jar}"

failed=0
for dir in spec/*/; do
  expect="$dir/expect-violation"
  for tla in "$dir"*.tla; do
    for cfg in "$dir"*.cfg; do
      name=$(basename "$cfg" .cfg)
      want=holds
      if [ -f "$expect" ] && grep -qx "$name" "$expect"; then want=violation; fi
      log=$(mktemp)
      set +e
      (cd "$dir" && java -XX:+UseParallelGC -cp "$TLA2TOOLS" tlc2.TLC -nowarning -workers auto \
        -metadir "${TMPDIR:-/tmp}/tlc-$name" -config "$(basename "$cfg")" "$(basename "$tla")") >"$log" 2>&1
      set -e
      if grep -q "Model checking completed. No error has been found" "$log"; then got=holds
      elif grep -q "Invariant .* is violated" "$log"; then got=violation
      else got=error; fi
      if [ "$got" = "$want" ]; then
        echo "ok   $dir$name: $got"
      else
        echo "FAIL $dir$name: wanted $want, got $got"; tail -30 "$log"; failed=1
      fi
    done
  done
done
exit $failed

#!/usr/bin/env bash
# Model-checks every TLA+ spec under spec/. A spec directory's configurations
# are named for their result: a configuration listed in its `expect-violation`
# file must make TLC find an invariant violation (they pin down what the model
# says is broken today); every other .cfg must hold.
#
# With an argument (spec/<name>/<config>.cfg) only that configuration is run,
# so CI can run each in its own job.
#
# Needs TLA2TOOLS to point at tla2tools.jar, and java.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TLA2TOOLS:?set TLA2TOOLS to tla2tools.jar}"

rm -f spec/*/*_TTrace_*  # a run that was cut short leaves them
failed=0
for dir in spec/*/; do
  expect="${dir}expect-violation"
  for cfg in "$dir"*.cfg; do
    [ -n "${1:-}" ] && [ "$1" != "$cfg" ] && continue
    name=$(basename "$cfg" .cfg)
    # The module a configuration checks: the .tla named like it, else the
    # directory's only one.
    if [ -f "$dir$name.tla" ]; then tla="$dir$name.tla"
    else
      tlas=()
      for f in "$dir"*.tla; do case $f in *_TTrace_*) ;; *) tlas+=("$f") ;; esac; done
      if [ "${#tlas[@]}" -ne 1 ]; then
        echo "FAIL $dir$name: ${#tlas[@]} .tla files and none named $name.tla"; failed=1; continue
      fi
      tla=${tlas[0]}
    fi
    want=holds
    if [ -f "$expect" ] && grep -qx "$name" "$expect"; then want=violation; fi
    log=$(mktemp)
    set +e
    (cd "$dir" && java -XX:+UseParallelGC -cp "$TLA2TOOLS" tlc2.TLC -nowarning -workers auto \
      -metadir "${TMPDIR:-/tmp}/tlc-$name" -config "$(basename "$cfg")" "$(basename "$tla")") >"$log" 2>&1
    set -e
    if grep -q "Model checking completed. No error has been found" "$log"; then got=holds
    elif grep -q "Invariant .* is violated" "$log"; then got=violation
    elif grep -q "Deadlock reached" "$log"; then got=deadlock
    elif grep -qE "Temporal properties were violated|Action property .* is violated" "$log"; then got=property-violation
    else got=error; fi
    if [ "$got" = "$want" ]; then
      echo "ok   $dir$name: $got"
    else
      echo "FAIL $dir$name: wanted $want, got $got"; tail -30 "$log"; failed=1
    fi
  done
done
rm -f spec/*/*_TTrace_*
exit $failed

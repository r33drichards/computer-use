#!/usr/bin/env bash
# Actual image regression: zero-cap UID1000 contract and existing legacy root
# containers with Docker's partial default set (no IPC_LOCK). Never add caps.
set -euo pipefail
image="${1:?image}"
out="${2:-keyring-capability-out}"
mkdir -p "$out"
name="keyring-capability-$$"
data=""
cleanup() {
  docker logs "$name" >"$out/container-last.log" 2>&1 || true
  docker rm -f "$name" >/dev/null 2>&1 || true
  [ -z "$data" ] || sudo rm -rf "$data"
}
trap cleanup EXIT
for mode in nonroot-zero legacy-partial; do
  data="$(mktemp -d)"
  args=()
  if [ "$mode" = nonroot-zero ]; then
    sudo chown 1000:1000 "$data"
    args=(--user 1000:1000 --cap-drop ALL --security-opt no-new-privileges)
  fi
  docker run -d --name "$name" "${args[@]}" --shm-size 1g \
    -e SESSION_MODE=1 -e DATA_DIR=/data -v "$data:/data/chrome" "$image" >/dev/null
  ready=""
  for _ in $(seq 1 120); do
    if docker exec "$name" /bin/bash -c '. /tmp/runtime/session-env; curl -fsS http://127.0.0.1:8081/healthz' >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  [ -n "$ready" ] || { echo "FAIL $mode health"; exit 1; }
  docker cp images/browser/test/keyring-smoke.sh "$name:/tmp/keyring-smoke.sh"
  docker cp images/browser/test/keyring-unlock.py "$name:/tmp/keyring-unlock.py"
  docker exec -i "$name" /bin/bash -s -- "$mode" <<'INSIDE' >"$out/$mode.log" 2>&1
set -euo pipefail
. /tmp/runtime/session-env
python3 - "$1" <<'PY'
import os, pathlib, sys
mode = sys.argv[1]
def status(pid):
    return dict(line.split(':', 1) for line in pathlib.Path('/proc', str(pid), 'status').read_text().splitlines() if ':' in line)
parent = status(os.getpid())
permitted = int(parent['CapPrm'], 16)
assert not permitted & (1 << 14), 'test must not grant IPC_LOCK'
assert (os.getuid() == 1000 and permitted == 0) if mode == 'nonroot-zero' else (os.getuid() == 0 and permitted != 0)
found = False
for p in pathlib.Path('/proc').iterdir():
    if not p.name.isdigit(): continue
    try:
        cmd = (p / 'cmdline').read_bytes()
        if b'gnome-keyring-daemon' not in cmd or b'--foreground' not in cmd: continue
        s = status(p.name)
        assert int(s['CapPrm'], 16) == 0 and int(s['CapEff'], 16) == 0, 'daemon must drop all unneeded capabilities'
        if mode == 'nonroot-zero': assert s['Uid'].split() == ['1000'] * 4
        found = True
    except FileNotFoundError: pass
assert found, 'supervised daemon required'
print('ok: ' + mode + ' daemon has zero permitted/effective capabilities')
PY
export TMPDIR="$(mktemp -d)"
export KEYRING_UNLOCK=/tmp/keyring-unlock.py
# Isolated test HOME/bus; encrypted persistence, wrong-password rejection,
# locked cold starts and manual unlock are still required in both modes.
# Scratch images have no /etc/dbus-1/session.conf. Use the same packaged
# session config as the desktop and the Nix encrypted smoke, not host defaults.
dbus-run-session --config-file="${DBUS_SESSION_CONF:?packaged session bus config required}" -- bash /tmp/keyring-smoke.sh
rm -rf "$TMPDIR"
INSIDE
  echo "ok: $mode capability and encrypted-keyring image regression"
  docker logs "$name" >"$out/$mode-container.log" 2>&1
  docker rm -f "$name" >/dev/null
  sudo rm -rf "$data"
  data=""
done

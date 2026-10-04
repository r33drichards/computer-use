#!/usr/bin/env bash
# Run under an isolated session bus, with a disposable HOME. Nix builds this
# before the image: the runtime's daemon must store secrets encrypted, keep
# them across a fresh daemon, and start locked without a login/password.
set -euo pipefail
: "${KEYRING_SERVER:?path to browser/keyring-server.sh}"
: "${KEYRING_UNLOCK:?path to test/keyring-unlock.py}"
export HOME="$TMPDIR/keyring-home"
export XDG_RUNTIME_DIR="$TMPDIR/keyring-runtime"
export GNOME_KEYRING_CONTROL="$XDG_RUNTIME_DIR/keyring"
mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
pid=""
cleanup() { [ -z "$pid" ] || kill "$pid" 2>/dev/null || true; }
trap cleanup EXIT

has_service() {
  dbus-send --session --print-reply --dest=org.freedesktop.DBus \
    /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner \
    string:org.freedesktop.secrets | grep -q 'boolean true'
}
start() {
  bash "$KEYRING_SERVER" >"$TMPDIR/keyring-daemon.log" 2>&1 &
  pid=$!
  wait_service
}
wait_service() {
  for _ in $(seq 1 100); do
    if has_service; then return; fi
    kill -0 "$pid"
    sleep 0.1
  done
  cat "$TMPDIR/keyring-daemon.log" >&2
  echo "Secret Service did not acquire its bus name" >&2
  exit 1
}
stop() {
  kill "$pid"
  wait "$pid" || true
  pid=""
  for _ in $(seq 1 100); do
    if ! has_service; then return; fi
    sleep 0.1
  done
  echo "Secret Service did not release its bus name" >&2
  exit 1
}
collection() {
  gdbus call --session --dest org.freedesktop.secrets \
    --object-path /org/freedesktop/secrets \
    --method org.freedesktop.Secret.Service.ReadAlias default |
    sed -n "s/.*objectpath '\([^']*\)'.*/\1/p"
}
locked() {
  gdbus call --session --dest org.freedesktop.secrets \
    --object-path "$(collection)" \
    --method org.freedesktop.DBus.Properties.Get org.freedesktop.Secret.Collection Locked |
    grep -q '<true>'
}

# Bound readiness for an already exported collection. This is not a way to
# export a new collection created through the login control socket.
wait_unlocked() {
  local path
  for _ in $(seq 1 100); do
    path="$(collection)"
    if [ -n "$path" ] && [ "$path" != / ] &&
      gdbus call --session --dest org.freedesktop.secrets \
        --object-path "$path" \
        --method org.freedesktop.DBus.Properties.Get org.freedesktop.Secret.Collection Locked \
        2>/dev/null | grep -q '<false>'; then
      return
    fi
    kill -0 "$pid"
    sleep 0.1
  done
  cat "$TMPDIR/keyring-daemon.log" >&2
  gdbus call --session --dest org.freedesktop.secrets \
    --object-path /org/freedesktop/secrets \
    --method org.freedesktop.Secret.Service.ReadAlias default >&2 || true
  gdbus introspect --session --dest org.freedesktop.secrets \
    --object-path /org/freedesktop/secrets/collection/login >&2 || true
  echo 'Login collection was not exported and unlocked after explicit unlock' >&2
  exit 1
}

start
[ "$(stat -c %a "$HOME/.local/share/keyrings")" = 700 ]
[ "$(stat -c %a "$GNOME_KEYRING_CONTROL")" = 700 ]
# Starting the runtime must not seed a plaintext/empty-password collection.
[ "$(collection)" = / ]
[ -z "$(find "$HOME/.local/share/keyrings" -name '*.keyring' -type f -print -quit)" ]
stop
# Test fixture only. GNOME 50's control-socket unlock creates a PKCS11
# collection but does not export a new Secret Service collection skeleton.
# gkd-main.c creates the stdin login keyring BEFORE initializing secrets when
# --unlock starts a fresh daemon; use that ordering, not a readiness sleep.
# See GNOME/gnome-keyring 50.0 daemon/gkd-main.c, daemon/login/gkd-login.c,
# daemon/control/gkd-control-server.c and daemon/dbus/gkd-secret-objects.c.
# No password is supplied to KEYRING_SERVER, including either cold start.
printf %s 'keyring-smoke-password' | gnome-keyring-daemon \
  --foreground --unlock --components=secrets \
  --control-directory="$GNOME_KEYRING_CONTROL" >"$TMPDIR/keyring-daemon.log" 2>&1 &
pid=$!
wait_service
echo "fixture: seeded encrypted login before Secret Service initialization"
wait_unlocked
stop
start
locked
echo "runtime: existing collection exported and cold-start locked"
# Explicitly unlock the existing encrypted collection via the control socket.
printf %s 'keyring-smoke-password' | python3 "$KEYRING_UNLOCK" ok
wait_unlocked
printf %s 'keyring-smoke-secret' | timeout 20 secret-tool store \
  --label='Computer Use smoke test' computeruse-smoke keyring
[ "$(timeout 20 secret-tool lookup computeruse-smoke keyring)" = keyring-smoke-secret ]
[ -n "$(find "$HOME/.local/share/keyrings" -name '*.keyring' -type f -print -quit)" ]
if grep -R -a -q 'keyring-smoke-secret' "$HOME/.local/share/keyrings"; then
  echo "Secret appeared unencrypted on disk" >&2
  exit 1
fi

stop
# A fresh runtime directory proves no control socket is needed for persistence.
export XDG_RUNTIME_DIR="$TMPDIR/keyring-runtime-restarted"
export GNOME_KEYRING_CONTROL="$XDG_RUNTIME_DIR/keyring"
mkdir -m 700 "$XDG_RUNTIME_DIR"
start
# The files survived, but memory did not: startup must not unlock them.
[ -n "$(find "$HOME/.local/share/keyrings" -type f -print -quit)" ]
locked
# A wrong nonempty password must be denied AND leave the collection locked.
printf %s 'keyring-smoke-wrong-password' | python3 "$KEYRING_UNLOCK" denied
locked
printf %s 'keyring-smoke-password' | python3 "$KEYRING_UNLOCK" ok
wait_unlocked
[ "$(timeout 20 secret-tool lookup computeruse-smoke keyring)" = keyring-smoke-secret ]
timeout 20 secret-tool clear computeruse-smoke keyring
echo 'ok: Secret Service, encrypted storage, restart persistence, locked startup'

#!/usr/bin/env bash
# Run under an isolated session bus, with a disposable HOME. Nix builds this
# before the image: the runtime's daemon must store secrets encrypted, keep
# them across a fresh daemon, and start locked without a login/password.
set -euo pipefail
: "${KEYRING_SERVER:?path to browser/keyring-server.sh}"
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
  for _ in $(seq 1 100); do
    if has_service; then return; fi
    kill -0 "$pid"
    sleep 0.1
  done
  cat "$TMPDIR/keyring-daemon.log" >&2
  echo "Secret Service did not acquire its bus name" >&2
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

# Control-socket unlock and Secret Service object registration need not finish
# together. Wait for the collection to be exported and unlocked before asking
# libsecret to store an item; a stale default alias alone is not readiness.
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
  echo 'Login collection was not exported and unlocked after explicit unlock' >&2
  exit 1
}

start
[ "$(stat -c %a "$HOME/.local/share/keyrings")" = 700 ]
[ "$(stat -c %a "$GNOME_KEYRING_CONTROL")" = 700 ]
# Starting the runtime must not seed a plaintext/empty-password collection.
[ "$(collection)" = / ]
[ -z "$(find "$HOME/.local/share/keyrings" -name '*.keyring' -type f -print -quit)" ]
# Test fixture only: GNOME Keyring reads a password from stdin, never argv.
printf %s 'keyring-smoke-password' | gnome-keyring-daemon --unlock \
  --control-directory="$GNOME_KEYRING_CONTROL" >/dev/null
wait_unlocked
printf %s 'keyring-smoke-secret' | timeout 20 secret-tool store \
  --label='Computer Use smoke test' computeruse-smoke keyring
[ "$(timeout 20 secret-tool lookup computeruse-smoke keyring)" = keyring-smoke-secret ]
[ -n "$(find "$HOME/.local/share/keyrings" -type f -print -quit)" ]
if grep -R -a -q 'keyring-smoke-secret' "$HOME/.local/share/keyrings"; then
  echo "Secret appeared unencrypted on disk" >&2
  exit 1
fi

kill "$pid"
wait "$pid" || true
pid=""
start
# The files survived, but memory did not: startup must not unlock them.
[ -n "$(find "$HOME/.local/share/keyrings" -type f -print -quit)" ]
locked
printf %s 'keyring-smoke-password' | gnome-keyring-daemon --unlock \
  --control-directory="$GNOME_KEYRING_CONTROL" >/dev/null
wait_unlocked
[ "$(timeout 20 secret-tool lookup computeruse-smoke keyring)" = keyring-smoke-secret ]
timeout 20 secret-tool clear computeruse-smoke keyring
echo 'ok: Secret Service, encrypted storage, restart persistence, locked startup'

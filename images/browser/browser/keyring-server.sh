#!/usr/bin/env bash
# Secret Service for this desktop only. The bus and HOME belong to the
# session; persistent keyrings live on its disk, control sockets do not.
# Never create an empty-password keyring or unlock one at container startup.
set -euo pipefail

: "${HOME:?set HOME to the session home}"
: "${XDG_RUNTIME_DIR:?set XDG_RUNTIME_DIR}"
: "${DBUS_SESSION_BUS_ADDRESS:?start the desktop session bus first}"
export GNOME_KEYRING_CONTROL="${GNOME_KEYRING_CONTROL:-$XDG_RUNTIME_DIR/keyring}"
install -d -m 700 "$HOME/.local/share/keyrings" "$GNOME_KEYRING_CONTROL"

# No PAM login or privileged wrapper in a session container. Foreground
# keeps the daemon under the entrypoint's core-process supervision. Only
# secrets: do not replace the session's SSH agent or start other components.
exec gnome-keyring-daemon --foreground --components=secrets \
  --control-directory="$GNOME_KEYRING_CONTROL"

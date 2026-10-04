#!/usr/bin/env bash
# Parent-managed credentials only. This script does not create/import keys.
set -euo pipefail
sums="${1:?usage: sign-checksums.sh path/to/VERSION_SHA256SUMS}"
: "${SIGNING_KEY_ID:?parent must select a real signing key}"
: "${GNUPGHOME:?parent must provide the authorized GPG home}"
[[ -f "$sums" && ! -e "$sums.sig" ]] || { echo 'missing checksums or existing signature' >&2; exit 1; }
python3 "$(dirname "$0")/check-release.py" "$sums"
gpg --batch --local-user "$SIGNING_KEY_ID" --output "$sums.sig" --detach-sign "$sums"
gpg --verify "$sums.sig" "$sums"

#!/usr/bin/env bash
# A real CLI schema check through a filesystem mirror, without server credentials.
set -euo pipefail
version="${1:?usage: check-install.sh VERSION RELEASE_DIR WORK_DIR [terraform|tofu]}"
release="$(cd "${2:?}" && pwd)"; work="${3:?}"; tf="${4:-terraform}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || exit 1
[[ ! -e "$work" ]] || { echo 'work directory must be new' >&2; exit 1; }
mkdir -p "$work"; work="$(cd "$work" && pwd)"
case "$(uname -s)" in Linux) os=linux;; Darwin) os=darwin;; *) exit 1;; esac
case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) exit 1;; esac
(cd "$release"; if command -v sha256sum >/dev/null; then sha256sum -c "terraform-provider-computeruse_${version}_SHA256SUMS"; else shasum -a 256 -c "terraform-provider-computeruse_${version}_SHA256SUMS"; fi)
for host in registry.terraform.io registry.opentofu.org; do
  dest="$work/mirror/$host/r33drichards/computeruse/$version/${os}_${arch}"; mkdir -p "$dest"
  unzip -q "$release/terraform-provider-computeruse_${version}_${os}_${arch}.zip" -d "$dest"
done
cat > "$work/rc" <<EOF
provider_installation {
  filesystem_mirror { path = "$work/mirror" }
}
EOF
cat > "$work/main.tf" <<EOF
terraform {
  required_providers {
    computeruse = { source = "r33drichards/computeruse", version = "=$version" }
  }
}
EOF
(cd "$work"; export TF_CLI_CONFIG_FILE="$work/rc"; "$tf" init -backend=false; "$tf" providers schema -json > schema.json)
python3 - "$work/schema.json" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))['provider_schemas']
assert len(s)==1 and next(iter(s)).endswith('/r33drichards/computeruse')
assert {'session','session_policy'} <= set(next(iter(s.values()))['resource_schemas'])
print('filesystem mirror provider schema check passed; no server lifecycle exercised')
PY

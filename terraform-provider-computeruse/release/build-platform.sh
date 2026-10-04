#!/usr/bin/env bash
# Run natively from a provider-root mirror, not the monorepo provider directory.
set -euo pipefail
version="${1:?usage: build-platform.sh VERSION OS ARCH [output-directory]}"
os="${2:?}"; arch="${3:?}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo 'invalid version (no v prefix)' >&2; exit 1; }
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
case "$(uname -s)" in Linux) host_os=linux;; Darwin) host_os=darwin;; *) exit 1;; esac
case "$(uname -m)" in x86_64|amd64) host_arch=amd64;; aarch64|arm64) host_arch=arm64;; *) exit 1;; esac
[[ "$os/$arch" == "$host_os/$host_arch" ]] || { echo 'native runner required; Go-only cross compilation is unsafe for CGO' >&2; exit 1; }
[[ -f sdk/Cargo.lock && -f sdk/go/go.mod ]] || { echo 'provider-root mirror with matching sdk/ required' >&2; exit 1; }
out="${4:-$root/dist/binaries}"; mkdir -p "$out/${os}_${arch}" "$root/.lib"
cargo build --manifest-path sdk/Cargo.toml --locked --release -p computeruse-sdk
cp "${CARGO_TARGET_DIR:-$root/sdk/target}/release/libcomputeruse.a" .lib/libcomputeruse.a
# Do not expose the cargo directory containing a cdylib to the Go linker.
export CGO_ENABLED=1 GOOS="$os" GOARCH="$arch" CGO_LDFLAGS="-L$root/.lib"
go vet ./...
go test -race ./...
binary="$out/${os}_${arch}/terraform-provider-computeruse_v$version"
go build -mod=readonly -trimpath -ldflags "-X main.version=$version" -o "$binary" .
if [[ "$os" == linux ]]; then
  readelf -l "$binary" > "$binary.elf.txt"
  readelf -d "$binary" >> "$binary.elf.txt"
  ! grep -q '/nix/store\|libcomputeruse\.so' "$binary.elf.txt" || { echo 'nonportable Nix or SDK dynamic dependency' >&2; exit 1; }
  ldd "$binary" > "$binary.runtime.txt"
  ! grep -q 'not found\|libcomputeruse' "$binary.runtime.txt"
else
  otool -L "$binary" > "$binary.runtime.txt"
  ! grep -q 'libcomputeruse\|/nix/store' "$binary.runtime.txt"
fi
printf '%s\n' "$binary"

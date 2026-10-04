"""Read-only fail-closed release gate; existing versions need manual reconciliation."""
import argparse
import re
import subprocess
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def require_absent(url):
    try:
        with urlopen(Request(url, headers={"User-Agent": "computeruse-release-preflight"}), timeout=30) as response:
            response.read(1)
    except HTTPError as error:
        error.close()
        if error.code == 404:
            return
        raise RuntimeError(f"Availability query failed: HTTP {error.code}") from error
    raise RuntimeError(f"Public object already exists: {url}; reconcile manually, never overwrite")


def check(version, sha):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected X.Y.Z and immutable commit")
    for name in ("computeruse-sdk-macros", "computeruse-sdk"):
        require_absent(f"https://crates.io/api/v1/crates/{name}/{version}")
    require_absent(f"https://pypi.org/pypi/computeruse-native-sdk/{version}/json")
    require_absent(f"https://registry.npmjs.org/computeruse/{version}")
    require_absent(f"https://api.github.com/repos/r33drichards/computer-use/releases/tags/sdk-v{version}")
    for tag in (f"sdk-v{version}", f"sdk/go/v{version}"):
        result = subprocess.run(["git", "ls-remote", "--exit-code", "--refs", "origin", f"refs/tags/{tag}"], capture_output=True, text=True)
        if result.returncode == 2:
            continue
        if result.returncode:
            raise RuntimeError(f"Tag query failed: exit {result.returncode}")
        subprocess.run(["git", "fetch", "--no-tags", "origin", f"refs/tags/{tag}"], check=True)
        actual = subprocess.check_output(["git", "rev-parse", "FETCH_HEAD^{commit}"], text=True).strip()
        if actual != sha:
            raise RuntimeError(f"{tag} source mismatch; refusing tag/release/assets overwrite")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    check(args.version, args.sha)

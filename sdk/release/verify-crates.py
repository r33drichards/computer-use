"""Compile real Cargo publication archives before any macros publication.
Uses only an extracted archived-source patch for the unpublished macros unit.
No public registry availability is implied; archive manifests remain normalized.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tarfile
import tomllib


def run(args, cwd, **kwargs):
    return subprocess.check_output(args, cwd=cwd, text=True, **kwargs)


def verify_dependency(manifest, version):
    dep = manifest["dependencies"]["computeruse-sdk-macros"]
    if dep.get("version") != version or any(key in dep for key in ("path", "git", "registry")):
        raise ValueError("SDK normalized macros dependency is not the matching registry version")


def verify(sdk, output):
    sdk, output = sdk.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    version = tomllib.loads((sdk / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    base_target = Path(os.environ.get("CARGO_TARGET_DIR", sdk / "target")).resolve()
    namespace = hashlib.sha256(str(output).encode()).hexdigest()[:24]
    target = base_target / "publication-unit-verification" / namespace
    cargo_env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    staged = output / "packaging-workspace"
    staged.mkdir()
    for filename in ("Cargo.toml", "Cargo.lock", "LICENSE"):
        shutil.copy2(sdk / filename, staged / filename)
    shutil.copytree(sdk / "crates", staged / "crates")
    units = []
    patch = None
    for name in ("computeruse-sdk-macros", "computeruse-sdk"):
        command = ["cargo", "package", "--allow-dirty", "--no-verify", "-p", name]
        if patch:
            command += ["--config", patch]
        run(command, staged, env=cargo_env)
        archive = target / "package" / f"{name}-{version}.crate"
        copied = output / archive.name
        copied.write_bytes(archive.read_bytes())
        with tarfile.open(copied) as tar:
            inventory = tar.getnames()
            tar.extractall(output / "extracted", filter="data")
        source = output / "extracted" / f"{name}-{version}"
        manifest = tomllib.loads((source / "Cargo.toml").read_text())
        if manifest["package"]["name"] != name or manifest["package"]["version"] != version:
            raise ValueError("Archive package identity mismatch")
        if name == "computeruse-sdk-macros":
            macro_source = source
            patch = "patch.crates-io.computeruse-sdk-macros.path=" + json.dumps(str(source))
        else:
            verify_dependency(manifest, version)
        units.append({"name":name,"version":version,"sha256":hashlib.sha256(copied.read_bytes()).hexdigest(),"archive":str(copied),"inventory":inventory})
    command = ["cargo", "metadata", "--format-version", "1", "--manifest-path", str(source / "Cargo.toml"), "--config", patch]
    metadata = json.loads(run(command, output, env=cargo_env))
    macro = next(p for p in metadata["packages"] if p["name"] == "computeruse-sdk-macros")
    if Path(macro["manifest_path"]).resolve() != macro_source / "Cargo.toml" or macro["version"] != version:
        raise ValueError("SDK did not resolve to the matching extracted archived macros unit")
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (output / "archive-receipt.json").write_text(json.dumps({"units":units,"macrosResolvedManifest":macro["manifest_path"],"verificationTarget":str(target),"method":"CLI patch.crates-io path points exclusively to extracted archived macros; not workspace source, not public registry proof"}, indent=2))
    for unit in units:
        manifest = output / "extracted" / f'{unit["name"]}-{version}' / "Cargo.toml"
        run(["cargo", "test", "--manifest-path", str(manifest), "--config", patch], output, env=cargo_env)
    (output / "VERIFIED").write_text("Both extracted archives compiled/tested; dependency identity checked\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk", type=Path, default=Path("sdk"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.sdk, args.output)

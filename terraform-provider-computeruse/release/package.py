#!/usr/bin/env python3
"""Assemble four native binaries. No builds, credentials, publishing or signing."""
import argparse, hashlib, json, os, re, stat, struct, zipfile
from pathlib import Path
PLATFORMS = ('linux_amd64', 'linux_arm64', 'darwin_amd64', 'darwin_arm64')
def valid_version(v):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?', v):
        raise ValueError('invalid version (no v prefix)')
    return v
def check_binary(path, platform):
    data = path.read_bytes()
    if not os.access(path, os.X_OK): raise ValueError(f'not executable: {path}')
    if platform.startswith('linux_'):
        machine = 62 if platform.endswith('amd64') else 183
        if len(data) < 20 or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != machine:
            raise ValueError(f'wrong ELF target: {path}')
    else:
        cpu = 0x01000007 if platform.endswith('amd64') else 0x0100000c
        if len(data) < 8 or data[:4] != b'\xcf\xfa\xed\xfe' or struct.unpack_from('<I', data, 4)[0] != cpu:
            raise ValueError(f'wrong Mach-O target: {path}')
    return data

def package(version, binaries, output, root, platforms=PLATFORMS):
    valid_version(version)
    name = f'terraform-provider-computeruse_v{version}'
    # Validate all inputs before creating the output; header checks are not execution tests.
    inputs = {p: check_binary(binaries / p / name, p) for p in platforms}
    licenses = {p: (root / p).read_bytes() for p in ('LICENSE', 'THIRD_PARTY.md')}
    licenses['SDK_LICENSE'] = (root / 'sdk/LICENSE').read_bytes()
    if output.exists(): raise ValueError('output must not already exist (avoid mixed releases)')
    output.mkdir(parents=True)
    for platform, data in inputs.items():
        archive = output / f'terraform-provider-computeruse_{version}_{platform}.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for filename, content in {name: data, **licenses}.items():
                info = zipfile.ZipInfo(filename, date_time=(1980,1,1,0,0,0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | (0o755 if filename == name else 0o644)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, content)
    manifest = output / f'terraform-provider-computeruse_{version}_manifest.json'
    manifest.write_text(json.dumps({'version':1,'metadata':{'protocol_versions':['6.0']}}, indent=2)+'\n')
    sums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(output.iterdir()))
    (output / f'terraform-provider-computeruse_{version}_SHA256SUMS').write_text(sums)

def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--platform', action='append', choices=PLATFORMS, help='Explicit partial-platform local smoke package; default requires all four targets')
    a.add_argument('version'); a.add_argument('binaries', type=Path); a.add_argument('output', type=Path)
    args=a.parse_args()
    package(args.version,args.binaries,args.output,Path(__file__).resolve().parent.parent, args.platform or PLATFORMS)
if __name__ == '__main__': main()

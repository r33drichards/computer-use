#!/usr/bin/env python3
"""Validate complete unsigned Registry release inventory before parent-controlled signing."""
import hashlib, json, re, sys, zipfile
from pathlib import Path
sums=Path(sys.argv[1]); match=re.fullmatch(r'terraform-provider-computeruse_([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?)_SHA256SUMS',sums.name)
if not match: raise ValueError('unexpected checksum filename')
v=match.group(1)
platforms=('linux_amd64','linux_arm64','darwin_amd64','darwin_arm64')
manifest=f'terraform-provider-computeruse_{v}_manifest.json'
expected={manifest}|{f'terraform-provider-computeruse_{v}_{p}.zip' for p in platforms}
rows={}
for line in sums.read_text().splitlines():
    digest,name=line.split('  ')
    if name in rows or not re.fullmatch('[0-9a-f]{64}',digest): raise ValueError('duplicate or invalid checksum')
    rows[name]=digest
if set(rows)!=expected: raise ValueError('complete four-platform ZIPs plus manifest required; partial smoke package cannot be signed')
for name,digest in rows.items():
    if hashlib.sha256((sums.parent/name).read_bytes()).hexdigest()!=digest: raise ValueError('checksum mismatch: '+name)
if json.loads((sums.parent/manifest).read_text())!={'version':1,'metadata':{'protocol_versions':['6.0']}}: raise ValueError('invalid protocol-6 manifest')
for p in platforms:
    with zipfile.ZipFile(sums.parent/f'terraform-provider-computeruse_{v}_{p}.zip') as z:
        binary=f'terraform-provider-computeruse_v{v}'
        if set(z.namelist())!={binary,'LICENSE','THIRD_PARTY.md','SDK_LICENSE'}: raise ValueError('unexpected ZIP inventory')
        if len(z.namelist())!=4 or (z.getinfo(binary).external_attr>>16)&0o777!=0o755: raise ValueError('duplicate entry or nonexecutable binary')
print('complete unsigned inventory and checksums verified; platform execution and licensing review remain separate gates')

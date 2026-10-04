#!/usr/bin/env python3
"""Check mirror layout and unchanged matching native/Go SDK inputs."""
import sys
from pathlib import Path
mirror, source = map(Path, sys.argv[1:])
assert '=> ./sdk/go' in (mirror/'go.mod').read_text()
assert 'module github.com/r33drichards/terraform-provider-computeruse' in (mirror/'go.mod').read_text()
assert '$(CURDIR)/sdk' in (mirror/'GNUmakefile').read_text()
assert 'filepath.Join("..", "..", "contracts", "policy", "examples")' in (mirror/'internal/provider/examples_test.go').read_text()
for f in mirror.rglob('*.go'):
    if 'sdk' not in f.relative_to(mirror).parts:
        assert 'github.com/r33drichards/computer-use/terraform-provider-computeruse' not in f.read_text(), str(f)
for part in ['sdk/Cargo.toml','sdk/Cargo.lock','sdk/LICENSE','sdk/README.md','sdk/crates','sdk/go']:
    p = source/part
    files = [p] if p.is_file() else list(p.rglob('*'))
    for f in files:
        if f.is_file():
            target = mirror/f.relative_to(source)
            assert target.read_bytes() == f.read_bytes(), str(target)
for f in (source/'docs/contracts/policy/examples').rglob('*'):
    if f.is_file(): assert (mirror/'contracts/policy/examples'/f.relative_to(source/'docs/contracts/policy/examples')).read_bytes()==f.read_bytes()
for part in ['LICENSE','THIRD_PARTY.md']:
    assert (mirror/part).read_bytes()==(source/part).read_bytes()
for f in (source/'terraform-provider-computeruse/docs').rglob('*'):
    if f.is_file(): assert (mirror/'docs'/f.relative_to(source/'terraform-provider-computeruse/docs')).read_bytes()==f.read_bytes()
assert not (mirror/'backend').exists()
assert not (mirror/'terraform-provider-metronome').exists()
print('mirror module/SDK/native/license/Registry-doc/contract input checks passed')
# Compare every provider source byte with the immutable snapshot after the
# same documented Copybara text transformations (not the mutable checkout).
provider_source = source/'terraform-provider-computeruse'
for f in provider_source.rglob('*'):
    rel=f.relative_to(provider_source)
    if not f.is_file() or any(x in rel.parts for x in ['.lib','dist','__pycache__']): continue
    data=f.read_bytes()
    replacements=[]
    if f.suffix=='.go' or str(rel)=='go.mod':
        replacements.append(('github.com/r33drichards/computer-use/terraform-provider-computeruse','github.com/r33drichards/terraform-provider-computeruse'))
    if str(rel)=='go.mod': replacements.append(('=> ../sdk/go','=> ./sdk/go'))
    if str(rel)=='GNUmakefile': replacements.extend([('$(CURDIR)/../sdk','$(CURDIR)/sdk'),('nix develop ..#sdk -c ','')])
    if str(rel) in ['internal/provider/examples_test.go','internal/fakeapi/fakeapi_test.go']: replacements.append(('filepath.Join("..", "..", "..", "docs", "contracts", "policy", "examples")','filepath.Join("..", "..", "contracts", "policy", "examples")'))
    if str(rel)=='README.md':
        replacements.extend([('../docs/contracts/policy','contracts/policy'),('../docs/terraform-provider.md','contracts/terraform-provider.md'),('docs/contracts/policy/backend-api.yaml','contracts/policy/backend-api.yaml'),('../sdk','sdk'),('nix develop ..#sdk -c ',''),('nix shell nixpkgs#opentofu -c ',''),("repository's `sdk` dev shell (`nix develop ..#sdk`, from this directory).",'a native toolchain on PATH (Go 1.26.8, Rust 1.91+, and a C compiler); see `release/README.md`.')])
    for before,after in replacements: data=data.replace(before.encode(),after.encode())
    assert (mirror/rel).read_bytes()==data, 'provider input mismatch: '+str(rel)
print('all provider bytes match immutable snapshot transformations')

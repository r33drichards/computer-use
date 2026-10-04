#!/usr/bin/env python3
"""Packaging mechanics only: synthetic headers are NOT native compatibility evidence."""
import hashlib, importlib.util, json, struct, tempfile, unittest, zipfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('package',Path(__file__).with_name('package.py'))
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
class Packaging(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name); self.b=self.root/'binaries'; self.v='0.1.0-rc.1'
        for part in ('LICENSE','THIRD_PARTY.md','sdk/LICENSE'):
            f=self.root/part; f.parent.mkdir(parents=True,exist_ok=True); f.write_text('test fixture license\n')
        for platform in p.PLATFORMS:
            f=self.b/platform/f'terraform-provider-computeruse_v{self.v}'; f.parent.mkdir(parents=True)
            if platform.startswith('linux'):
                data=bytearray(64); data[:6]=b'\x7fELF\x02\x01'; struct.pack_into('<H',data,18,62 if platform.endswith('amd64') else 183)
            else:
                data=bytearray(32); data[:4]=b'\xcf\xfa\xed\xfe'; struct.pack_into('<I',data,4,0x01000007 if platform.endswith('amd64') else 0x0100000c)
            f.write_bytes(data); f.chmod(0o755)
    def test_archives_manifest_checksums_reproducible(self):
        a=self.root/'a'; b=self.root/'b'; p.package(self.v,self.b,a,self.root); p.package(self.v,self.b,b,self.root)
        self.assertEqual({f.name:f.read_bytes() for f in a.iterdir()},{f.name:f.read_bytes() for f in b.iterdir()})
        sums=(a/f'terraform-provider-computeruse_{self.v}_SHA256SUMS').read_text().splitlines()
        self.assertEqual(len(sums),5)
        for line in sums:
            digest,name=line.split('  '); self.assertEqual(digest,hashlib.sha256((a/name).read_bytes()).hexdigest())
        m=a/f'terraform-provider-computeruse_{self.v}_manifest.json'
        self.assertEqual(json.loads(m.read_text()),{'version':1,'metadata':{'protocol_versions':['6.0']}})
        for platform in p.PLATFORMS:
            with zipfile.ZipFile(a/f'terraform-provider-computeruse_{self.v}_{platform}.zip') as z:
                name=f'terraform-provider-computeruse_v{self.v}'
                self.assertEqual(set(z.namelist()),{name,'LICENSE','THIRD_PARTY.md','SDK_LICENSE'})
                self.assertEqual((z.getinfo(name).external_attr>>16)&0o777,0o755)
    def test_missing_binary(self):
        next(self.b.rglob('*_v*')).unlink()
        with self.assertRaises(FileNotFoundError): p.package(self.v,self.b,self.root/'out',self.root)
        self.assertFalse((self.root/'out').exists())
    def test_wrong_architecture(self):
        f=self.b/'linux_arm64'/f'terraform-provider-computeruse_v{self.v}'
        f.write_bytes((self.b/'linux_amd64'/f.name).read_bytes())
        with self.assertRaises(ValueError): p.package(self.v,self.b,self.root/'out',self.root)
    def test_nonexecutable(self):
        next(self.b.rglob('*_v*')).chmod(0o644)
        with self.assertRaises(ValueError): p.package(self.v,self.b,self.root/'out',self.root)
    def test_invalid_version(self):
        for v in ['v1.0.0','../0.1.0','1.2.3;sh','']:
            with self.assertRaises(ValueError): p.valid_version(v)
    def test_existing_output(self):
        out=self.root/'out'; out.mkdir()
        with self.assertRaises(ValueError): p.package(self.v,self.b,out,self.root)
    def test_complete_inventory_gate(self):
        import subprocess, sys
        out=self.root/'full'; p.package(self.v,self.b,out,self.root)
        sums=out/f'terraform-provider-computeruse_{self.v}_SHA256SUMS'
        check=Path(__file__).with_name('check-release.py')
        subprocess.run([sys.executable,str(check),str(sums)],check=True,capture_output=True)
        (out/f'terraform-provider-computeruse_{self.v}_manifest.json').write_text('{}')
        self.assertNotEqual(subprocess.run([sys.executable,str(check),str(sums)],capture_output=True).returncode,0)
    def test_partial_smoke_cannot_pass_signing_inventory(self):
        import subprocess, sys
        out=self.root/'partial'; p.package(self.v,self.b,out,self.root,['linux_amd64'])
        sums=out/f'terraform-provider-computeruse_{self.v}_SHA256SUMS'
        self.assertEqual(len(sums.read_text().splitlines()),2)
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('check-release.py')),str(sums)],capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'partial smoke package cannot be signed',result.stderr)
if __name__=='__main__': unittest.main()

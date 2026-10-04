import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
spec = importlib.util.spec_from_file_location('receipt',Path(__file__).with_name('module_fixture_receipt.py'))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class SafeReceipt(unittest.TestCase):
    def test_actual_atomic_private_write_and_tighten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'out.json'; path.write_text('old'); path.chmod(0o666)
            mod.private_write(path, {'synthetic':True})
            self.assertEqual(json.loads(path.read_text()), {'synthetic':True})
            self.assertEqual(path.stat().st_mode & 0o7777,0o600)
            self.assertEqual(path.stat().st_uid,os.getuid())
    def test_symlink_hardlink_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'target'; target.write_text('synthetic owner')
            path=Path(tmp)/'receipt'; path.symlink_to(target)
            with self.assertRaises(OSError): mod.private_write(path, {})
            self.assertEqual(target.read_text(),'synthetic owner')
            path.unlink(); os.link(target,path)
            with self.assertRaises(OSError): mod.private_write(path,{})
            self.assertEqual(target.read_text(),'synthetic owner')
    def test_byte_cap_refuses_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'out.json'; path.write_text('old')
            with self.assertRaises(ValueError): mod.private_write(path,{'x':'x'*8192})
            self.assertEqual(path.read_text(),'old')
    def test_fixed_exception_reason_never_serializes_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt=mod.Receipt.__new__(mod.Receipt); receipt.path=Path(tmp)/'out.json'
            receipt.data={'status':'running','stage':'module'}
            receipt.fail(ValueError('synthetic must-not-copy response/body/header'))
            text=receipt.path.read_text()
            self.assertNotIn('must-not-copy',text)
            self.assertEqual(json.loads(text)['reason'],'schema-or-json')
            with self.assertRaises(ValueError): receipt.mark('arbitrary raw server error')
            with self.assertRaises(ValueError): receipt.counter('counterAfter',-1)

if __name__=='__main__': unittest.main()

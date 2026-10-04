import json
import os
from pathlib import Path
import tempfile
import unittest
from private_diagnostic_file import write_private_json

class PrivateFile(unittest.TestCase):
    def test_normal_and_existing_mode_tightening(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'receipt.json'
            write_private_json(path, '{"synthetic": true}')
            self.assertTrue(json.loads(path.read_text())['synthetic'])
            path.chmod(0o666)
            write_private_json(path, '{"synthetic": false}')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(json.loads(path.read_text())['synthetic'])
    def test_symlink_and_hardlink_refuse_without_target_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'target'; target.write_text('synthetic-owner')
            path = Path(tmp)/'receipt.json'; path.symlink_to(target)
            with self.assertRaises(OSError): write_private_json(path, '{}')
            self.assertEqual(target.read_text(), 'synthetic-owner')
            path.unlink(); os.link(target, path)
            with self.assertRaises(OSError): write_private_json(path, '{}')
            self.assertEqual(target.read_text(), 'synthetic-owner')
    def test_nonregular_refused_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'fifo'; os.mkfifo(path)
            with self.assertRaises(OSError): write_private_json(path, '{}')

if __name__ == '__main__': unittest.main()

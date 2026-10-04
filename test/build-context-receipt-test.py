import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('receipt', Path(__file__).with_name('build-context-receipt.py'))
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
class Receipt(unittest.TestCase):
    def test_regular_inputs_hashes_and_missing_or_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r.subprocess, 'check_output', return_value='a'*40):
            root = Path(tmp); context = root/'images/mcp-js'; context.mkdir(parents=True)
            (context/'Dockerfile').write_text('COPY start.sh /start.sh')
            (context/'start.sh').write_text('synthetic'); (context/'start.sh').chmod(0o755)
            result = r.receipt(root, 'mcp-js', 'images/mcp-js', '', 'a'*40)
            self.assertEqual(result['resolvedContext'], 'images/mcp-js')
            self.assertEqual(result['startScript']['mode'], '0o755')
            self.assertEqual(len(result['startScript']['sha256']), 64)
            with self.assertRaises(ValueError): r.receipt(root, 'mcp-js', '../outside', '', 'a'*40)
            with self.assertRaises(ValueError): r.receipt(root, 'mcp-js', 'images/mcp-js', '', 'b'*40)
            (context/'start.sh').unlink()
            with self.assertRaises(OSError): r.receipt(root, 'mcp-js', 'images/mcp-js', '', 'a'*40)
            (context/'start.sh').symlink_to(context/'Dockerfile')
            with self.assertRaises(ValueError): r.receipt(root, 'mcp-js', 'images/mcp-js', '', 'a'*40)
if __name__ == '__main__': unittest.main()

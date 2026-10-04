import importlib.util
from pathlib import Path
import tempfile
import json
import os
import subprocess
import sys
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
    def test_structured_missing_start_retains_binding_without_raw_exception(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r.subprocess, 'check_output', return_value='a'*40):
            root = Path(tmp); context = root/'images/mcp-js'; context.mkdir(parents=True)
            (context/'Dockerfile').write_text('synthetic')
            result = r.structured_receipt(root, 'mcp-js', 'images/mcp-js', '', 'a'*40, '123', 'build', 'failure')
            self.assertEqual(result['stage'], 'start-script')
            self.assertEqual(result['reason'], 'missing-input')
            self.assertEqual(result['testOutcome'], 'failure')
            self.assertEqual(result['source'], 'a'*40)
            self.assertEqual(result['runId'], '123')
            self.assertIn('sha256', result['dockerfile'])
            self.assertLess(len(json.dumps(result).encode()), 8192)
            with patch.object(r, 'receipt', side_effect=ValueError('synthetic-private-Bearer')):
                bad = r.structured_receipt(root, 'mcp-js', 'images/mcp-js', '', 'a'*40)
                self.assertNotIn('synthetic-private', json.dumps(bad))
                self.assertEqual(bad['reason'], 'validation-refused')
            invalid = r.structured_receipt(root, 'mcp-js', 'bad\nsynthetic-private', '', 'a'*40)
            self.assertEqual(invalid['reason'], 'invalid-input')
            self.assertNotIn('synthetic-private', json.dumps(invalid))

    def test_cli_failure_persists_private_valid_artifact_and_nonzero_gate(self):
        script = Path(__file__).with_name('build-context-receipt.py').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'receipt.json'
            env = {'PATH': os.defpath, 'BUILD_NAME': 'mcp-js', 'BUILD_CONTEXT': 'missing-synthetic-context', 'EXPECTED_SOURCE': 'a'*40, 'RECEIPT_FILE': str(path), 'RECEIPT_RUN_ID': '123', 'RECEIPT_JOB': 'build'}
            done = subprocess.run([sys.executable, '-B', str(script)], cwd=tmp, env=env, capture_output=True, timeout=5)
            self.assertEqual(done.returncode, 1)
            self.assertEqual(done.stderr, b'')
            result = json.loads(path.read_bytes())
            self.assertEqual(result['stage'], 'context')
            self.assertEqual(result['status'], 'error')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertLess(path.stat().st_size, 8192)
            self.assertEqual(result, json.loads(done.stdout))

    def test_workflow_uploads_on_failure_without_weakening_build(self):
        workflow = Path('.github/workflows/images.yml').read_text()
        build = workflow[workflow.index('  build:'):workflow.index('  publish:')]
        self.assertLess(build.index('id: context_test'), build.index('- name: Path-context receipt\n'))
        self.assertIn("if: ${{ !cancelled() && steps.source.outcome == 'success' }}", build)
        self.assertIn('name: path-context-${{ github.job }}-${{ matrix.name }}-${{ steps.source.outputs.sha }}-${{ github.run_id }}', build)
        self.assertIn('RECEIPT_TEST_OUTCOME: ${{ steps.context_test.outcome }}', build)
        self.assertNotIn('continue-on-error', build)
        self.assertNotIn('if: always()', build[build.index('      - name: Build\n'):])

if __name__ == '__main__': unittest.main()

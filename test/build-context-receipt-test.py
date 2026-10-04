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
            (context/'Dockerfile').write_text('COPY --chmod=755 start.sh /usr/local/bin/start.sh')
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
            (context/'Dockerfile').write_text('COPY --chmod=755 start.sh /usr/local/bin/start.sh')
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

    def test_both_layouts_and_legacy_root_mismatch_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r.subprocess, 'check_output', return_value='a'*40):
            root = Path(tmp); context = root/'images/mcp-js'; context.mkdir(parents=True)
            dockerfile = context/'Dockerfile'
            start = context/'start.sh'; start.write_text('synthetic'); start.chmod(0o755)
            dockerfile.write_text('COPY --chmod=755 start.sh /usr/local/bin/start.sh\n')
            subdir = r.receipt(root, 'mcp-js', 'images/mcp-js', '', 'a'*40)
            self.assertEqual(subdir['startSource'], 'start.sh')
            mismatch = r.structured_receipt(root, 'mcp-js', '.', 'images/mcp-js/Dockerfile', 'a'*40)
            self.assertEqual(mismatch['status'], 'error')
            self.assertEqual(mismatch['stage'], 'start-script')
            self.assertEqual(mismatch['declaredStartSource'], 'start.sh')
            self.assertEqual(mismatch['expectedStartSource'], 'images/mcp-js/start.sh')
            self.assertTrue(start.is_file())  # Not an absent committed file.
            dockerfile.write_text('COPY --chmod=755 images/mcp-js/start.sh /usr/local/bin/start.sh\n')
            (root/'.dockerignore').write_text('**\n')
            (context/'Dockerfile.dockerignore').write_text('**\n!images/mcp-js/**\n')
            root_result = r.receipt(root, 'mcp-js', '.', 'images/mcp-js/Dockerfile', 'a'*40)
            self.assertEqual(root_result['startScript']['path'], 'images/mcp-js/start.sh')
            self.assertEqual(root_result['startSource'], 'images/mcp-js/start.sh')
            self.assertEqual(root_result['effectiveIgnore']['path'], 'images/mcp-js/Dockerfile.dockerignore')
            wrong_subdir = r.structured_receipt(root, 'mcp-js', 'images/mcp-js', '', 'a'*40)
            self.assertEqual(wrong_subdir['status'], 'error')

    def test_actual_matrix_and_unset_file_expression_match_source_checkout(self):
        matrix = json.loads(Path('.github/image-build-matrix.json').read_text())
        mcp = next(x for x in matrix if x['name'] == 'mcp-js')
        self.assertEqual((mcp['context'], mcp.get('file') or ''), ('.', 'images/mcp-js/Dockerfile'))
        self.assertFalse(any(x['name'] == 'mcp-js-skills' for x in matrix))
        workflow = Path('.github/workflows/images.yml').read_text()
        changes = workflow[:workflow.index('  build:')]
        self.assertIn('ref: ${{ github.event.pull_request.head.sha || github.sha }}', changes)
        self.assertIn('cat .github/image-build-matrix.json', changes)
        self.assertNotIn("table='[", changes)
        self.assertIn('context: ${{ matrix.context }}', workflow)
        self.assertIn('file: ${{ matrix.file }}', workflow)
        # The missing file expression yields empty/default, never repo root.
        self.assertEqual({'context': 'images/mcp-js'}.get('file') or '', '')

    def test_matrix_definition_hash_binding_and_mixed_inputs_refused(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r.subprocess, 'check_output', return_value='a'*40):
            root = Path(tmp); context = root/'images/mcp-js'; context.mkdir(parents=True)
            (context/'Dockerfile').write_text('COPY --chmod=755 images/mcp-js/start.sh /usr/local/bin/start.sh\n')
            (context/'start.sh').write_text('synthetic'); (context/'start.sh').chmod(0o755)
            (root/'.github').mkdir()
            definition = root/'.github/image-build-matrix.json'
            definition.write_text(json.dumps([{'name': 'mcp-js', 'context': '.', 'file': 'images/mcp-js/Dockerfile'}]))
            good = r.structured_receipt(root, 'mcp-js', '.', 'images/mcp-js/Dockerfile', 'a'*40)
            self.assertEqual(good['status'], 'success')
            self.assertEqual(good['definitionSource'], 'a'*40)
            self.assertEqual(len(good['matrixDefinition']['sha256']), 64)
            wrong = r.structured_receipt(root, 'mcp-js', 'images/mcp-js', '', 'a'*40)
            self.assertEqual(wrong['stage'], 'matrix-definition')
            self.assertEqual(wrong['status'], 'error')

if __name__ == '__main__': unittest.main()

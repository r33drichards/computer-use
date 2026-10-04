import json
import runpy
import unittest
from unittest.mock import patch

REVISION = 'a' * 40


class WaitTests(unittest.TestCase):
    def wait(self, operation_revision, phase):
        app = {'status': {'sync': {'revision': REVISION, 'status': 'Synced'}, 'health': {'status': 'Healthy'}, 'operationState': {'phase': phase, 'syncResult': {'revision': operation_revision}}}}
        with patch('sys.argv', ['wait.py', REVISION, '1']), patch('subprocess.check_output', return_value=json.dumps(app)), patch('time.sleep'):
            with self.assertRaises(SystemExit) as result:
                runpy.run_path('hack/gitops/wait.py', run_name='__main__')
        return result.exception.code

    def test_successful_sync(self):
        self.assertEqual(self.wait(REVISION, 'Succeeded'), 0)

    def test_failed_current_revision_is_rejected_even_when_resources_healthy(self):
        self.assertEqual(self.wait(REVISION, 'Failed'), 'Argo CD sync failed')

    def test_restoring_existing_resources_does_not_require_a_new_sync_operation(self):
        self.assertEqual(self.wait('b' * 40, 'Failed'), 0)


if __name__ == '__main__':
    unittest.main()

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('diagnostics', Path(__file__).with_name('canary-pod-diagnostics.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

class Diagnostics(unittest.TestCase):
    def test_invalid_or_unowned_pod_is_not_collected(self):
        with patch.object(d, 'command') as command:
            with self.assertRaises(ValueError): d.collect('../other')
            command.assert_not_called()
            command.return_value = json.dumps({'metadata': {'name': 's-abcdefghij', 'labels': {}}, 'spec': {}})
            with self.assertRaises(ValueError): d.collect('s-abcdefghij')
            self.assertEqual(command.call_count, 1)

    def test_only_owned_pod_whitelisted_fields_and_sanitized_logs(self):
        pod = {'metadata': {'name': 's-abcdefghij', 'uid': 'owned', 'labels': {'app': 'browserjs-session'}},
               'spec': {'containers': [{'name': 'browser', 'env': [{'name': 'secret', 'value': 'do-not-copy'}], 'image': 'browser:test'},
                                        {'name': 'mcp-js', 'image': 'mcp:test'}, {'name': 'unrelated'}]}, 'status': {'phase': 'Running'}}
        calls = []
        def command(*args):
            calls.append(args)
            if args[:2] == ('get', 'pod'): return json.dumps(pod)
            if args[:2] == ('get', 'events'): return json.dumps({'items': [
                {'involvedObject': {'uid': 'owned'}, 'reason': 'Unhealthy'},
                {'involvedObject': {'uid': 'other'}, 'message': 'do-not-copy'}]})
            return 'Bearer abc bjs_fixture_token eyJabc.def.ghi'
        with patch.object(d, 'command', command):
            text = d.collect('s-abcdefghij')
        self.assertNotIn('do-not-copy', text)
        self.assertNotIn('fixture_token', text)
        self.assertNotIn('Bearer abc', text)
        self.assertNotIn('eyJabc', text)
        self.assertEqual(len(json.loads(text)['events']), 1)
        self.assertTrue(all('unrelated' not in c for c in calls))
        self.assertIn(('get', 'events', '--field-selector', 'involvedObject.uid=owned', '-o', 'json'), calls)

if __name__ == '__main__': unittest.main()

import importlib.util
import json
from pathlib import Path
import subprocess
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

    def test_log_field_errors_are_explicit_without_exception_disclosure(self):
        pod = {'metadata': {'name': 's-abcdefghij', 'uid': 'owned', 'labels': {'app': 'browserjs-session'}},
               'spec': {'containers': [{'name': 'browser'}, {'name': 'mcp-js'}]}}
        def command(*args):
            if args[:2] == ('get', 'pod'): return json.dumps(pod)
            if args[:2] == ('get', 'events'): return '{"items": []}'
            if args[3] == 'browser':
                if '--previous' in args:
                    raise subprocess.TimeoutExpired('Bearer synthetic-private', 8, output='bjs_synthetic_private', stderr='eyJabc.def.ghi')
                raise RuntimeError('Bearer synthetic-private bjs_synthetic_private')
            return 'Bearer synthetic-private'
        with patch.object(d, 'command', command): text = d.collect('s-abcdefghij')
        logs = json.loads(text)['logs']
        self.assertEqual(logs['browser'], {'status': 'error', 'reason': 'command-failed'})
        self.assertEqual(logs['browser-previous'], {'status': 'unavailable', 'reason': 'timeout'})
        self.assertIn('[redacted]', logs['mcp-js'])
        self.assertNotIn('synthetic-private', text)
        self.assertNotIn('synthetic_private', text)
        self.assertNotIn('eyJabc', text)

    def test_known_no_previous_is_distinct_from_arbitrary_failure(self):
        pod = {'metadata': {'name': 's-abcdefghij', 'uid': 'owned', 'labels': {'app': 'browserjs-session'}},
               'spec': {'containers': [{'name': 'browser'}, {'name': 'mcp-js'}]},
               'status': {'containerStatuses': [{'name': 'browser', 'restartCount': 0}, {'name': 'mcp-js', 'restartCount': 1}]}}
        calls = []
        def command(*args):
            calls.append(args)
            if args[:2] == ('get', 'pod'): return json.dumps(pod)
            if args[:2] == ('get', 'events'): return '{"items": []}'
            raise RuntimeError('synthetic-private')
        with patch.object(d, 'command', command): result = json.loads(d.collect('s-abcdefghij'))
        self.assertEqual(result['logs']['browser-previous'], {'status': 'unavailable', 'reason': 'no-previous-container'})
        self.assertEqual(result['logs']['mcp-js-previous'], {'status': 'error', 'reason': 'command-failed'})
        self.assertFalse(any('--previous' in x and 'browser' in x for x in calls))
        self.assertNotIn('synthetic-private', json.dumps(result))

    def test_events_and_messages_are_bounded_and_log_overflow_explicit(self):
        pod = {'metadata': {'name': 's-abcdefghij', 'uid': 'owned', 'labels': {'app': 'browserjs-session'}}, 'spec': {'containers': [{'name': 'browser'}]}}
        def command(*args):
            if args[:2] == ('get', 'pod'): return json.dumps(pod)
            if args[:2] == ('get', 'events'): return json.dumps({'items': [{'involvedObject': {'uid': 'owned'}, 'message': 'Bearer synthetic-private ' + 'x' * 2000} for _ in range(100)]})
            raise d.OutputLimitExceeded('byte-limit')
        with patch.object(d, 'command', command): result = json.loads(d.collect('s-abcdefghij'))
        self.assertEqual(len(result['events']), 32)
        self.assertTrue(result['eventsTruncated'])
        self.assertTrue(all(len(e['message']) <= 1024 and e['messageTruncated'] for e in result['events']))
        self.assertEqual(result['logs']['browser'], {'status': 'truncated', 'reason': 'byte-limit'})
        self.assertNotIn('synthetic-private', json.dumps(result))

    def test_oversized_pod_json_is_not_partially_parsed_or_disclosed(self):
        with patch.object(d, 'command', side_effect=d.OutputLimitExceeded('byte-limit')):
            result = json.loads(d.collect('s-abcdefghij'))
        self.assertEqual(result, {'pod': 's-abcdefghij', 'status': 'truncated', 'reason': 'byte-limit'})

if __name__ == '__main__': unittest.main()

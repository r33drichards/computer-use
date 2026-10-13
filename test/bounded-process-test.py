import json
import subprocess
import sys
import unittest
from bounded_process import run_bounded, OutputLimitExceeded

class Bounds(unittest.TestCase):
    def test_single_line_stream_exceeding_cap_is_not_returned(self):
        with self.assertRaises(OutputLimitExceeded):
            run_bounded([sys.executable, '-c', 'import sys; sys.stdout.write("x"*1000000)'], timeout=2, max_bytes=1024)
    def test_exact_cap_and_non_utf8(self):
        result = run_bounded([sys.executable, '-c', 'import os; os.write(1, b"x"*1023+bytes([255]))'], timeout=2, max_bytes=1024)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout), 1024)
        self.assertTrue(result.stdout.endswith('\ufffd'))
    def test_timeout_discards_untrusted_stderr(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded([sys.executable, '-c', 'import sys,time; print("synthetic-private", file=sys.stderr); time.sleep(3)'], timeout=0.05, max_bytes=1024)
    def test_descendant_pipe_timeout_terminates_only_own_group(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded([sys.executable, '-c', 'import subprocess; subprocess.Popen(["sleep", "3"])'], timeout=0.05, max_bytes=1024)
    def test_json_is_never_parsed_as_truncated_prefix(self):
        with self.assertRaises(OutputLimitExceeded):
            run_bounded([sys.executable, '-c', 'print("["+"0,"*100000+"0]")'], timeout=2, max_bytes=1024)

if __name__ == '__main__': unittest.main()

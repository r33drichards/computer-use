import fnmatch
import json
from pathlib import Path
import re
import subprocess
import unittest

class Trigger(unittest.TestCase):
    def test_helper_only_events_and_all_images_selection_execute_actual_filter(self):
        text = Path('.github/workflows/images.yml').read_text()
        patterns = ('test/build-context-receipt*.py','test/ci-source-binding*','test/image-helper-trigger-test.py')
        for pattern in patterns:
            self.assertEqual(text.split('jobs:')[0].count('"'+pattern+'"'), 2)
        regex = re.search(r"if touches '([^']+)'; then", text).group(1)
        branch = re.search(r"if touches '[^']+'; then\n\s+# [^\n]+\n\s+(wanted=\([^\n]+\))", text).group(1)
        script = 'wanted=(); if grep -Eq "$1"; then '+branch+'; fi; printf "%s\n" "${wanted[@]}"'
        expected = sorted(x['name'] for x in json.loads(Path('.github/image-build-matrix.json').read_text()))
        for file in ('test/build-context-receipt.py','test/build-context-receipt-test.py','test/ci-source-binding.sh','test/ci-source-binding.test.mjs','test/image-helper-trigger-test.py'):
            result = subprocess.run(['bash','-c',script,'filter',regex],input=file+'\n',text=True,capture_output=True,timeout=5)
            self.assertEqual(result.returncode, 0, file)
            self.assertEqual(sorted(result.stdout.split()), expected, file)
            self.assertTrue(any(fnmatch.fnmatchcase(file, x) for x in patterns))
        unrelated = subprocess.run(['bash','-c',script,'filter',regex],input='docs/unrelated.md\n',text=True,capture_output=True,timeout=5)
        self.assertEqual(unrelated.returncode,0)
        self.assertEqual(unrelated.stdout.strip(),'')
    def test_publish_security_and_immutable_definition_retained(self):
        text = Path('.github/workflows/images.yml').read_text()
        self.assertNotIn('pull_request_target',text)
        self.assertIn("github.event_name != 'pull_request' && github.ref == 'refs/heads/main'",text)
        self.assertIn('persist-credentials: false',text)
        self.assertIn('cat .github/image-build-matrix.json',text)

if __name__ == '__main__': unittest.main()

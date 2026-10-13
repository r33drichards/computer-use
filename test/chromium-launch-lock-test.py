import os
from pathlib import Path
import subprocess
import tempfile
import unittest

class LaunchLock(unittest.TestCase):
    def test_contention_refuses_launch_and_preserves_foreign_lock(self):
        source = Path('images/browser/browser/session-chromium.sh').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'chromium-start.lock').mkdir(); (root/'profile').mkdir()
            (root/'profile/SingletonLock').write_text('synthetic-owner')
            (root/'bin').mkdir()
            for name, body in [('seq', 'echo 1'), ('sleep', ':')]:
                p = root/'bin'/name; p.write_text('#!/bin/sh\n'+body+'\n'); p.chmod(0o700)
            env = dict(os.environ, CHROMIUM_BIN='/bin/false', XDG_RUNTIME_DIR=tmp, BROWSER_PROFILE_DIR=str(root/'profile'), PATH=str(root/'bin')+':'+os.environ['PATH'])
            result = subprocess.run(['bash', '-c', source], env=env, capture_output=True, text=True, timeout=2)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('lock unavailable', result.stderr)
            self.assertTrue((root/'chromium-start.lock').is_dir())
            self.assertEqual((root/'profile/SingletonLock').read_text(), 'synthetic-owner')
    def test_owned_release_failure_and_replaced_inode(self):
        source = Path('images/browser/browser/session-chromium.sh').read_text()
        block = source[source.index('lock="$RUNTIME/chromium-start.lock"'):source.index('if [ -n "$(browser_pids)" ];')]
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, RUNTIME=tmp)
            for ending in ['exit 13', 'release_launch_lock; trap - EXIT; exit 0']:
                subprocess.run(['bash', '-c', 'set -euo pipefail; '+block+ending], env=env, timeout=2)
                self.assertFalse((Path(tmp)/'chromium-start.lock').exists())
            result = subprocess.run(['bash', '-c', 'set -euo pipefail; '+block+'mv "$lock" "$lock-owned"; mkdir "$lock"; exit 0'], env=env, timeout=2)
            self.assertEqual(result.returncode, 0)
            self.assertTrue((Path(tmp)/'chromium-start.lock').exists())

if __name__ == '__main__': unittest.main()

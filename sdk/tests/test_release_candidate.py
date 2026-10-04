"""Offline release guard regression tests; never contact or push to a public remote.
Run: python3 -m unittest discover -s sdk/tests -v
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/sdk-release.yml"

class ReleaseGuardTests(unittest.TestCase):
    def test_package_names_and_oidc(self):
        py = tomllib.loads((ROOT / "sdk/python/pyproject.toml").read_text())
        self.assertEqual(py["project"]["name"], "computeruse-native-sdk")
        self.assertEqual(py["tool"]["maturin"]["module-name"], "computeruse")
        for path, name in [("computeruse", "computeruse-sdk"), ("computeruse-macros", "computeruse-sdk-macros")]:
            manifest = tomllib.loads((ROOT / f"sdk/crates/{path}/Cargo.toml").read_text())
            self.assertEqual(manifest["package"]["name"], name)
        self.assertEqual(json.loads((ROOT / "sdk/js/package.json").read_text())["name"], "computeruse")
        self.assertIn("module github.com/r33drichards/computer-use/sdk/go", (ROOT / "sdk/go/go.mod").read_text())
        text = WORKFLOW.read_text()
        job = text.split("  publish-pypi:\n", 1)[1].split("  publish-npm:\n", 1)[0]
        self.assertIn("    environment: pypi\n", job)
        self.assertIn("      id-token: write", job)
        self.assertEqual(WORKFLOW.name, "sdk-release.yml")
        self.assertIn("--find-links dist/wheels computeruse-native-sdk", text)

    def exercise(self, kind, query_error=0, fetch_error=0):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote, local, bin_dir = base / "remote.git", base / "local", base / "bin"
            bin_dir.mkdir()
            env = dict(os.environ, HOME=str(base), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            real_git = shutil.which("git")
            def git(*args, cwd=None):
                return subprocess.check_output([real_git, *args], cwd=cwd, env=env, stderr=subprocess.DEVNULL, text=True).strip()
            git("init", "--bare", str(remote))
            git("init", str(local))
            git("config", "user.name", "Offline fixture", cwd=local)
            git("config", "user.email", "fixture@example.invalid", cwd=local)
            git("commit", "--allow-empty", "-m", "fixture", cwd=local)
            sha = git("rev-parse", "HEAD", cwd=local)
            git("remote", "add", "origin", str(remote), cwd=local)
            tag = "sdk/go/v0.1.0"
            if kind != "absent":
                if kind == "conflict":
                    git("commit", "--allow-empty", "-m", "conflict", cwd=local)
                if kind == "annotated":
                    git("tag", "-a", tag, "-m", "annotated fixture", cwd=local)
                else:
                    git("tag", tag, cwd=local)
                git("push", "origin", f"refs/tags/{tag}", cwd=local)  # LOCAL bare fixture only
                git("tag", "-d", tag, cwd=local)
            log = base / "calls"
            wrapper = bin_dir / "git"
            wrapper.write_text(textwrap.dedent(r"""
                #!/usr/bin/env python3
                import json, os, subprocess, sys
                args = sys.argv[1:]
                with open(os.environ['CALL_LOG'], 'a') as log:
                    log.write(json.dumps(args) + '\n')
                if args[0] == 'ls-remote' and int(os.environ['QUERY_ERROR']):
                    sys.exit(int(os.environ['QUERY_ERROR']))
                if args[0] == 'fetch' and int(os.environ['FETCH_ERROR']):
                    sys.exit(int(os.environ['FETCH_ERROR']))
                if args[0] in ('tag', 'push'):
                    sys.exit(0)  # recording stub, no publication
                sys.exit(subprocess.call([os.environ['REAL_GIT'], *args]))
                """))
            wrapper.write_text(wrapper.read_text().lstrip())
            wrapper.chmod(0o755)
            env.update(PATH=str(bin_dir) + os.pathsep + env["PATH"], REAL_GIT=real_git, CALL_LOG=str(log),
                       QUERY_ERROR=str(query_error), FETCH_ERROR=str(fetch_error), VERSION="0.1.0", GITHUB_SHA=sha)
            text = WORKFLOW.read_text()
            guard = text.split("          # Accept an existing remote Go tag", 1)[1].split("          (cd dist/go", 1)[0]
            create = text.split('          if [ "$go_tag_exists" = false ]; then', 1)[1]
            script = 'set -euo pipefail\n' + textwrap.dedent(guard.split("\n", 1)[1]) + '\nif [ "$go_tag_exists" = false ]; then\n' + textwrap.dedent(create)
            result = subprocess.run(["bash", "-c", script], cwd=local, env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return result, calls, sha

    def test_absent_tag(self):
        result, calls, sha = self.exercise("absent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["tag", "sdk/go/v0.1.0", sha], calls)
        self.assertIn(["push", "origin", "refs/tags/sdk/go/v0.1.0"], calls)
        self.assertNotIn("fetch", [c[0] for c in calls])

    def check_existing(self, kind):
        result, calls, _ = self.exercise(kind)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["rev-parse", "FETCH_HEAD^{commit}"], calls)
        self.assertNotIn("tag", [c[0] for c in calls])
        self.assertNotIn("push", [c[0] for c in calls])

    def test_same_commit_lightweight_tag(self):
        self.check_existing("lightweight")

    def test_same_commit_annotated_tag(self):
        self.check_existing("annotated")

    def test_conflicting_commit(self):
        result, calls, _ = self.exercise("conflict")
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing to move it", result.stdout)
        self.assertNotIn("push", [c[0] for c in calls])

    def test_remote_query_error(self):
        result, calls, _ = self.exercise("absent", query_error=128)
        self.assertEqual(result.returncode, 128)
        self.assertEqual(len(calls), 1)

    def test_fetch_error(self):
        result, calls, _ = self.exercise("lightweight", fetch_error=128)
        self.assertEqual(result.returncode, 128)
        self.assertEqual([c[0] for c in calls], ["ls-remote", "fetch"])

if __name__ == "__main__":
    unittest.main()

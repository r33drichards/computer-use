"""Offline fixtures for release safety, NOT native library validation."""
import importlib.util
from pathlib import Path
from unittest import TestCase, mock
from urllib.error import HTTPError, URLError
import subprocess

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("preflight", ROOT / "sdk/release/preflight.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

class PreflightTests(TestCase):
    def test_404_is_only_absence(self):
        with mock.patch.object(gate, "urlopen", side_effect=HTTPError("url",404,"",{},None)):
            gate.require_absent("https://example.invalid")

    def test_existing_object_refused(self):
        with mock.patch.object(gate, "urlopen"):
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                gate.require_absent("https://example.invalid")

    def test_server_and_auth_errors_fail_closed(self):
        for code in (401,403,429,500):
            with self.subTest(code=code), mock.patch.object(gate, "urlopen", side_effect=HTTPError("url",code,"",{},None)):
                with self.assertRaises(RuntimeError):
                    gate.require_absent("https://example.invalid")

    def test_transport_failure_propagates(self):
        with mock.patch.object(gate, "urlopen", side_effect=URLError("offline")):
            with self.assertRaises(URLError):
                gate.require_absent("https://example.invalid")

    def exercise(self, code=2, sha=None):
        with mock.patch.object(gate, "require_absent") as absent, mock.patch.object(gate.subprocess, "run", return_value=subprocess.CompletedProcess([],code)) as run, mock.patch.object(gate.subprocess, "check_output", return_value=(sha or "a"*40)+"\n"):
            gate.check("0.1.0", "a"*40)
            return absent, run

    def test_new_release_queries_all_names(self):
        absent, run = self.exercise()
        self.assertEqual(absent.call_count, 5)
        self.assertEqual(run.call_count, 2)
        urls = [call.args[0] for call in absent.call_args_list]
        self.assertTrue(any("computeruse-native-sdk" in url for url in urls))
        self.assertTrue(any("computeruse-sdk-macros" in url for url in urls))

    def test_same_commit_tags_allowed(self):
        self.exercise(0)

    def test_mismatched_source_refused(self):
        with self.assertRaisesRegex(RuntimeError, "source mismatch"):
            self.exercise(0, "b"*40)

    def test_tag_query_error_refused(self):
        with self.assertRaisesRegex(RuntimeError, "exit 128"):
            self.exercise(128)

    def test_invalid_identity_refused(self):
        with self.assertRaises(ValueError):
            gate.check("0.1.0", "main")

    def test_workflow_disabled_and_no_overwrite(self):
        text = (ROOT / ".github/workflows/sdk-release.yml").read_text()
        self.assertIn("Publication disabled pending final immutable commit approval", text)
        self.assertNotIn("--clobber", text)
        self.assertNotIn("  push:", text)
        for job in ("publish-crates", "publish-pypi", "publish-npm", "github-release"):
            block = text.split("  " + job + ":", 1)[1].split("    steps:", 1)[0]
            self.assertIn("publication-preflight", block)

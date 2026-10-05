"""Tests of the scripts that gate CI: hack/coverage-report.py and
hack/ci-coverage.sh. (hack/tlc-check.sh needs Java and TLC; CI runs it on the
real specs.)"""
import json
import os
import pathlib
import runpy
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]


def report(current, baseline, max_drop=None):
    """Runs coverage-report.py in-process; returns (exit code, markdown)."""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / "cur").mkdir()
        for name, pct in current.items():
            (d / "cur" / f"{name}.json").write_text(json.dumps({"pct": pct}))
        base = "-"
        if baseline is not None:
            (d / "base.json").write_text(json.dumps(baseline))
            base = str(d / "base.json")
        argv = ["coverage-report.py", str(d / "cur"), base, str(d / "out.md")]
        if max_drop is not None:
            argv.append(str(max_drop))
        old = sys.argv
        sys.argv = argv
        try:
            runpy.run_path(str(REPO / "hack/coverage-report.py"), run_name="__main__")
            code = 0
        except SystemExit as e:
            code = e.code or 0
        finally:
            sys.argv = old
        combined = json.loads((d / "cur" / "combined.json").read_text())
        return code, (d / "out.md").read_text(), combined


class CoverageReport(unittest.TestCase):
    def test_no_baseline_is_all_new(self):
        code, md, _ = report({"a": 50.0}, None)
        self.assertEqual(code, 0)
        self.assertIn("new", md)

    def test_small_drop_passes(self):
        code, _, _ = report({"a": 59.5}, {"a": 60.0})
        self.assertEqual(code, 0)

    def test_drop_over_threshold_fails(self):
        code, md, _ = report({"a": 58.0}, {"a": 60.0})
        self.assertEqual(code, 1)
        self.assertIn("❌", md)

    def test_threshold_is_configurable(self):
        self.assertEqual(report({"a": 58.0}, {"a": 60.0}, 5)[0], 0)

    def test_rise_passes(self):
        self.assertEqual(report({"a": 70.0}, {"a": 60.0})[0], 0)

    def test_component_missing_from_results_fails(self):
        code, md, _ = report({"a": 60.0}, {"a": 60.0, "b": 10.0})
        self.assertEqual(code, 1)
        self.assertIn("no result", md)

    def test_new_component_passes_and_joins_combined(self):
        code, _, combined = report({"a": 60.0, "b": 10.0}, {"a": 60.0})
        self.assertEqual(code, 0)
        self.assertEqual(combined, {"a": 60.0, "b": 10.0})


def run_coverage_check(files, workflows):
    """ci-coverage.sh on a throwaway git repo with `files` and one workflow."""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        for f in files:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text("")
        (d / ".github/workflows").mkdir(parents=True)
        (d / ".github/workflows/w.yml").write_text(workflows)
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "add", "-A"], cwd=d, check=True)
        return subprocess.run(
            [str(REPO / "hack/ci-coverage.sh")], cwd=d, env={**os.environ, "ROOT": str(d)},
            capture_output=True, text=True)


class CiCoverage(unittest.TestCase):
    def test_paths_entry_covers(self):
        r = run_coverage_check(["app/go.mod"], 'on:\n  pull_request:\n    paths:\n      - "app/**"\n')
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_working_directory_covers(self):
        r = run_coverage_check(["app/go.mod"], "jobs:\n  t:\n    defaults:\n      run:\n        working-directory: app\n")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_unmentioned_component_fails(self):
        r = run_coverage_check(["app/go.mod"], "name: x\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("app", r.stdout)

    def test_comment_does_not_cover(self):
        r = run_coverage_check(["app/go.mod"], "# - app/**\nname: x\n")
        self.assertEqual(r.returncode, 1)

    def test_negated_path_does_not_cover(self):
        r = run_coverage_check(["app/go.mod"], 'paths:\n  - "!app/**"\n')
        self.assertEqual(r.returncode, 1)

    def test_longer_path_containing_it_does_not_cover(self):
        r = run_coverage_check(["web/package.json"], 'paths:\n  - "sdk/web/**"\n')
        self.assertEqual(r.returncode, 1)

    def test_parent_directory_covers(self):
        r = run_coverage_check(["sdk/crates/x/Cargo.toml"], 'paths:\n  - "sdk/**"\n')
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_root_manifest_needs_its_own_path_entry(self):
        self.assertEqual(run_coverage_check(["go.mod"], 'paths:\n  - "backend/**"\n').returncode, 1)
        self.assertEqual(run_coverage_check(["go.mod"], 'paths:\n  - "go.mod"\n').returncode, 0)

    def test_spec_needs_the_tlc_script(self):
        self.assertEqual(run_coverage_check(["spec/a/A.tla"], "name: x\n").returncode, 1)
        self.assertEqual(run_coverage_check(["spec/a/A.tla"], "run: hack/tlc-check.sh\n").returncode, 0)


if __name__ == "__main__":
    unittest.main()

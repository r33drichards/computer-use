#!/usr/bin/env python3
"""Compares this run's coverage with the baseline from main, as a table.

    coverage-report.py CURRENT_DIR BASELINE_FILE|- OUT_MD [MAX_DROP]

CURRENT_DIR holds one `<component>.json` per component, `{"pct": 71.2}`.
BASELINE_FILE is the combined `{component: pct}` the last run on main wrote,
or `-` if there is none. OUT_MD gets the table (the pull request comment).
The combined current results are written to CURRENT_DIR/combined.json.
Exits 1 when a component dropped by more than MAX_DROP points (default 1.0).
See docs/ci-notes.md.
"""
import json
import pathlib
import sys

current_dir, baseline_file, out_md = sys.argv[1:4]
max_drop = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0

current = {
    p.stem: json.loads(p.read_text())["pct"]
    for p in sorted(pathlib.Path(current_dir).glob("*.json"))
    if p.stem != "combined"
}
baseline = {}
if baseline_file != "-" and pathlib.Path(baseline_file).exists():
    baseline = json.loads(pathlib.Path(baseline_file).read_text())

rows, failed = [], []
for name, pct in current.items():
    base = baseline.get(name)
    if base is None:
        rows.append(f"| {name} | {pct:.1f}% | new | ✅ |")
        continue
    delta = pct - base
    bad = delta < -max_drop
    if bad:
        failed.append(name)
    rows.append(f"| {name} | {pct:.1f}% | {delta:+.1f} (main {base:.1f}%) | {'❌' if bad else '✅'} |")
for name in sorted(set(baseline) - set(current)):
    rows.append(f"| {name} | — | no result (main {baseline[name]:.1f}%) | ❌ |")
    failed.append(name)

md = ["<!-- coverage-report -->", "### Code coverage", "",
      "| Component | Coverage | Change | |", "|---|---|---|---|", *rows, ""]
if failed:
    md.append(f"Coverage dropped by more than {max_drop:g} points, or a result is missing: {', '.join(failed)}.")
else:
    md.append(f"No component dropped by more than {max_drop:g} points.")
md.append("\nWhat is measured, and what is not: `docs/ci-notes.md`.")
pathlib.Path(out_md).write_text("\n".join(md) + "\n")
pathlib.Path(current_dir, "combined.json").write_text(json.dumps(current, indent=1))
print("\n".join(md))
sys.exit(1 if failed else 0)

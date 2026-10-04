#!/usr/bin/env python3
"""Require every check of the merged PR's tested head before publishing."""
import json
import os
import subprocess
import sys
import time

repo = os.environ['GITHUB_REPOSITORY']
sha = sys.argv[1]
def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/{path}']))
prs = [p for p in api(f'commits/{sha}/pulls') if p.get('merged_at') and p.get('merge_commit_sha') == sha and p['base']['ref'] == 'main']
if not prs:
    sys.exit('Automatic production releases require a reviewed, merged pull request')
head = prs[0]['head']['sha']
deadline = time.monotonic() + 1200
while time.monotonic() < deadline:
    checks = api(f'commits/{head}/check-runs?per_page=100')['check_runs']
    # Reruns may leave old records. Use the newest check of each name.
    latest = {}
    for check in sorted(checks, key=lambda c: c['id']):
        latest[check['name']] = check
    if not latest:
        sys.exit('No checks were found for the merged pull request')
    failures = [c['name'] for c in latest.values() if c['status'] == 'completed' and c['conclusion'] not in {'success', 'skipped', 'neutral'}]
    if failures:
        sys.exit('Release refused: failed PR checks: ' + ', '.join(failures))
    if all(c['status'] == 'completed' for c in latest.values()):
        print('All merged PR checks passed')
        sys.exit(0)
    print('Waiting for merged PR checks', flush=True)
    time.sleep(20)
sys.exit('PR checks did not finish before the deadline')

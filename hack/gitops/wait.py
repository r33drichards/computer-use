#!/usr/bin/env python3
"""Wait for the exact desired Git revision, failing on degradation or timeout."""
import json
import os
import subprocess
import sys
import time

revision = sys.argv[1]
deadline = time.monotonic() + int(sys.argv[2] if len(sys.argv) > 2 else 1200)
while time.monotonic() < deadline:
    app = json.loads(subprocess.check_output(['kubectl', '-n', 'argocd', 'get', 'application', os.environ.get('ARGOCD_APP', 'computer-use-production'), '-o', 'json']))
    status = app.get('status', {})
    sync = status.get('sync', {})
    operation = status.get('operationState', {})
    phase = operation.get('phase', '')
    operation_revision = operation.get('syncResult', {}).get('revision')
    health = status.get('health', {}).get('status', '')
    print(f'Argo CD: revision={sync.get("revision", "pending")} sync={sync.get("status")} health={health} operation={phase}', flush=True)
    if operation_revision == revision and phase in {'Failed', 'Error'}:
        sys.exit('Argo CD sync failed')
    if sync.get('revision') == revision:
        if health == 'Degraded':
            sys.exit('Argo CD release degraded')
        if sync.get('status') == 'Synced' and health == 'Healthy' and not app.get('operation') and phase not in {'Running', 'Terminating'}:
            sys.exit(0)
    time.sleep(10)
sys.exit('Argo CD release did not become healthy before the deadline')

#!/usr/bin/env python3
"""Emit structured deployment-failure logs for Cloud Monitoring email alerts."""
import json
import ssl
import urllib.request
from pathlib import Path

root = Path('/var/run/secrets/kubernetes.io/serviceaccount')
url = 'https://kubernetes.default.svc/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/computer-use-production'
request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + (root / 'token').read_text().strip()})
with urllib.request.urlopen(request, context=ssl.create_default_context(cafile=str(root / 'ca.crt')), timeout=20) as response:
    app = json.load(response)
status = app.get('status', {})
operation = status.get('operationState', {})
health = status.get('health', {}).get('status')
failed = (operation.get('syncResult', {}).get('revision') == status.get('sync', {}).get('revision') and operation.get('phase') in {'Failed', 'Error'}) or health == 'Degraded'
print(json.dumps({'severity':'ERROR' if failed else 'INFO', 'event':'deployment_failed' if failed else 'deployment_healthy', 'application':app['metadata']['name'], 'revision':status.get('sync', {}).get('revision', ''), 'message':operation.get('message', health or 'Pending')}), flush=True)

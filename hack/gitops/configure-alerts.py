#!/usr/bin/env python3
"""Idempotently configure deployment-failure emails in Cloud Monitoring."""
import argparse
import json
import subprocess
import urllib.request


def configure(project, email):
    token = subprocess.check_output(['gcloud', 'auth', 'print-access-token'], text=True).strip()
    root = f'https://monitoring.googleapis.com/v3/projects/{project}'
    def request(path, body=None, method=None):
        req = urllib.request.Request(root + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                     headers={'Authorization':'Bearer ' + token, 'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    channels = request('/notificationChannels').get('notificationChannels', [])
    channel = next((c for c in channels if c['type'] == 'email' and c.get('labels', {}).get('email_address') == email), None)
    if channel is None:
        channel = request('/notificationChannels', {'type':'email', 'displayName':'Computer Use deployment failures', 'labels':{'email_address':email}, 'enabled':True})
    policy = {'displayName':'Computer Use production deployment failed', 'enabled':True, 'combiner':'OR',
              'documentation':{'mimeType':'text/markdown', 'content':'A Computer Use production release failed. Check [production release workflows](https://github.com/r33drichards/computer-use/actions/workflows/gitops-release.yml) for the release and rollback result. Argo CD application: `computer-use-production`.'},
              'conditions':[{'displayName':'Deployment failure', 'conditionMatchedLog':{'filter':'jsonPayload.event="deployment_failed" AND jsonPayload.application="computer-use-production"', 'labelExtractors':{'revision':'EXTRACT(jsonPayload.revision)'}}}],
              'alertStrategy':{'notificationRateLimit':{'period':'300s'}, 'autoClose':'1800s'},
              'notificationChannels':[channel['name']]}
    existing = next((p for p in request('/alertPolicies').get('alertPolicies', []) if p['displayName'] == policy['displayName']), None)
    if existing:
        policy['name'] = existing['name']
        policy = request('/alertPolicies/' + existing['name'].rsplit('/', 1)[1], policy, 'PATCH')
    else:
        policy = request('/alertPolicies', policy)
    print(json.dumps({'channel':channel['name'], 'policy':policy['name'], 'email':email}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default='browserjs-sessions')
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    configure(args.project, args.email)

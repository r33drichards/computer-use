#!/usr/bin/env python3
"""Render a release from reviewed manifests and this build's immutable images."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

import yaml

IMAGES = {'backend', 'browser', 'mcp-js', 'site', 'policy-operator', 'billing-operator'}
DIGEST = re.compile(r'^us-west1-docker\.pkg\.dev/browserjs-sessions/browserjs/([a-z-]+)@sha256:[0-9a-f]{64}$')


def validate_image(name, image):
    match = DIGEST.fullmatch(image)
    if name not in IMAGES or not match or match[1] != name:
        raise ValueError(f'invalid release image: {name}')


def render(source, previous, artifacts, output):
    images = dict(previous['images'])
    for name, image in images.items():
        validate_image(name, image)
    for path in sorted(artifacts.glob('**/image.json')):
        item = json.loads(path.read_text())
        if item['source_sha'] != source:
            raise ValueError('image artifact is from another commit')
        if item['name'] == 'mcp-js-skills':
            continue  # The opt-in skills rollout owns this separate image.
        validate_image(item['name'], item['image'])
        images[item['name']] = item['image']
    if not re.fullmatch(r'[0-9a-f]{40}', source):
        raise ValueError('invalid source commit')
    subprocess.run(['hack/pin-images.sh', *[f'{n}={v.split("@")[1]}' for n, v in images.items()]], check=True)
    subprocess.run(['hack/pin-images.sh', '--check'], check=True)
    if os.environ.get('PREVIEWS_ENABLED') == 'true':
        subprocess.run(['python3', 'hack/preview.py', 'prepare-edge'], check=True)
    docs = list(yaml.safe_load_all(subprocess.check_output(['kubectl', 'kustomize', 'deploy/gke'], text=True)))
    # Mutable controller-owned resources and bootstrap infrastructure are not
    # release payloads. The existing manual workflow installs their CRDs.
    excluded = {'CustomResourceDefinition', 'Namespace', 'StorageClass', 'ClusterRole', 'ClusterRoleBinding', 'PodSnapshotStorageConfig'}
    docs = [d for d in docs if d and d['kind'] not in excluded]
    for d in docs:
        meta = d.setdefault('metadata', {})
        meta.setdefault('annotations', {})['argocd.argoproj.io/sync-wave'] = '0'
        # Install durable storage, connectivity and namespaced permissions
        # before the operator: its startup requires Redis and pod watches.
        if d['kind'] in {'NetworkPolicy', 'Role', 'RoleBinding'} or (meta['name'] == 'webhook-redis' and d['kind'] in {'Service', 'StatefulSet'}):
            meta['annotations']['argocd.argoproj.io/sync-wave'] = '-2'
        if d['kind'] == 'Deployment' and meta['name'] in {'policy-operator', 'opa'}:
            meta['annotations']['argocd.argoproj.io/sync-wave'] = '-1'
        if d['kind'] == 'AnalysisTemplate' and meta['name'] == 'release-canary':
            container = d['spec']['metrics'][0]['provider']['job']['spec']['template']['spec']['containers'][0]
            container['command'][2] = container['command'][2].replace('exit 0', 'exit 1')
            for env in container['env']:
                if env['name'] == 'CANARY_API_TOKEN':
                    env['valueFrom']['secretKeyRef'].pop('optional', None)
    docs.append({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'release-canary','namespace':'browserjs-sessions','annotations':{'argocd.argoproj.io/sync-wave':'-2'}},'data':{'canary.py':Path('test/canary.py').read_text()}})
    output.mkdir(parents=True, exist_ok=True)
    (output / 'manifests.yaml').write_text(yaml.safe_dump_all(docs, sort_keys=False))
    (output / 'release.json').write_text(json.dumps({'source_sha': source, 'images': images}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    render(args.source, json.loads(args.previous.read_text()), args.artifacts, args.output)

"""Grow existing session PVCs; use only the mounted Kubernetes credentials."""
import json
import os
import re
import ssl
import time
import urllib.request
from decimal import Decimal

TARGET = 32 * 1024**3


def bytes_of(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGTPE]i?|[kmun]?)", value)
    if not match:
        raise ValueError(f"Unsupported storage quantity: {value}")
    number, unit = match.groups()
    scales = {"": 1, "k": 1000, "m": Decimal('.001'), "u": Decimal('.000001'), "n": Decimal('.000000001')}
    for index, prefix in enumerate('KMGTPE', 1):
        scales[prefix] = 1000**index
        scales[prefix + 'i'] = 1024**index
    return Decimal(number) * scales[unit]


def is_session(pvc):
    return (pvc['spec'].get('storageClassName') == 'browserjs-zonal'
            and re.fullmatch(r'data-s-[a-z0-9]+', pvc['metadata']['name']) is not None
            and any(owner.get('kind') == 'Sandbox'
                    and owner.get('apiVersion', '').startswith('agents.x-k8s.io/')
                    for owner in pvc['metadata'].get('ownerReferences', [])))


def main():
    credentials = '/var/run/secrets/kubernetes.io/serviceaccount'
    with open(credentials + '/namespace') as stream:
        namespace = stream.read().strip()
    context = ssl.create_default_context(cafile=credentials + '/ca.crt')
    base = f"https://{os.environ['KUBERNETES_SERVICE_HOST']}:{os.environ['KUBERNETES_SERVICE_PORT_HTTPS']}/api/v1/namespaces/{namespace}/persistentvolumeclaims"

    def request(path='', patch=None):
        with open(credentials + '/token') as stream:
            token = stream.read().strip()
        headers = {'Authorization': 'Bearer ' + token}
        data = None
        if patch is not None:
            headers['Content-Type'] = 'application/merge-patch+json'
            data = json.dumps(patch).encode()
        req = urllib.request.Request(base + path, data=data, headers=headers,
                                     method='PATCH' if patch is not None else 'GET')
        with urllib.request.urlopen(req, context=context, timeout=30) as response:
            return json.load(response)

    pending = set()
    for pvc in request()['items']:
        if not is_session(pvc) or pvc['metadata'].get('deletionTimestamp'):
            continue
        name = pvc['metadata']['name']
        requested = bytes_of(pvc['spec']['resources']['requests']['storage'])
        if requested < TARGET:
            # Reject a concurrent change rather than accidentally shrink a larger request.
            request('/' + name, {'metadata': {'resourceVersion': pvc['metadata']['resourceVersion']},
                                'spec': {'resources': {'requests': {'storage': '32Gi'}}}})
            print(f'{name}: requested 32Gi', flush=True)
        if bytes_of(pvc.get('status', {}).get('capacity', {}).get('storage', '0')) < TARGET:
            pending.add(name)
    deadline = time.monotonic() + int(os.environ.get('WAIT_SECONDS', '900'))
    while pending and time.monotonic() < deadline:
        for pvc in request()['items']:
            name = pvc['metadata']['name']
            if name in pending and bytes_of(pvc.get('status', {}).get('capacity', {}).get('storage', '0')) >= TARGET:
                pending.remove(name)
                print(f'{name}: capacity confirmed at least 32Gi', flush=True)
        if pending:
            time.sleep(10)
    if pending:
        raise RuntimeError('Expansion not confirmed; inspect PVC conditions and mount stopped sessions: ' + ', '.join(sorted(pending)))
    print('All selected session PVC capacities confirmed at least 32Gi.', flush=True)


if __name__ == '__main__':
    main()

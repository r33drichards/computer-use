"""Keep claimed sessions and warm capacity within a three-disk budget."""
import json
import os
import ssl
import time
import urllib.request


def desired_replicas(sandboxes, claims, total=3, reserved=0):
    warm = set()
    occupied = set()
    for item in sandboxes:
        name = item['metadata']['name']
        pooled = any(ref.get('kind') == 'SandboxWarmPool' and ref.get('name') == 's'
                     for ref in item['metadata'].get('ownerReferences', []))
        if pooled and not item['metadata'].get('deletionTimestamp'):
            warm.add(name)
        else:
            occupied.add(name)
    # A released disk still consumes quota until its claim disappears. Also
    # count suspended sessions, cold starts and any retained recovery claims.
    for claim in claims:
        name = claim['metadata']['name']
        if name.startswith('data-s-') and name[5:] not in warm:
            occupied.add(name[5:])
    return max(0, total - reserved - len(occupied))


def main():
    credentials = '/var/run/secrets/kubernetes.io/serviceaccount'
    with open(credentials + '/namespace') as stream:
        namespace = stream.read().strip()
    context = ssl.create_default_context(cafile=credentials + '/ca.crt')
    root = f"https://{os.environ['KUBERNETES_SERVICE_HOST']}:{os.environ['KUBERNETES_SERVICE_PORT_HTTPS']}"

    def api(path, patch=None):
        with open(credentials + '/token') as stream:
            token = stream.read().strip()
        headers = {'Authorization': 'Bearer ' + token}
        data = None
        if patch is not None:
            headers['Content-Type'] = 'application/merge-patch+json'
            data = json.dumps(patch).encode()
        request = urllib.request.Request(root + path, headers=headers, data=data,
                                         method='PATCH' if patch is not None else 'GET')
        with urllib.request.urlopen(request, context=context, timeout=20) as response:
            return json.load(response)

    pool_path = f'/apis/extensions.agents.x-k8s.io/v1beta1/namespaces/{namespace}/sandboxwarmpools/s'
    while True:
        try:
            sandboxes = api(f'/apis/agents.x-k8s.io/v1beta1/namespaces/{namespace}/sandboxes')['items']
            claims = api(f'/api/v1/namespaces/{namespace}/persistentvolumeclaims')['items']
            wanted = desired_replicas(sandboxes, claims, reserved=int(os.getenv('RESERVED_SLOTS', '0')))
            pool = api(pool_path)
            if pool['spec'].get('replicas') != wanted:
                api(pool_path, {'metadata': {'resourceVersion': pool['metadata']['resourceVersion']},
                                'spec': {'replicas': wanted}})
                print(f'Warm slots: {wanted}; total budget: 3', flush=True)
        except Exception as error:
            # Fail closed: API errors never increase the pool. Retry from fresh state.
            print(f'Reconcile failed: {error}', flush=True)
        time.sleep(2)


if __name__ == '__main__':
    main()

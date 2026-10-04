"""Keep claimed sessions and warm capacity within a three-disk budget."""
import json
from datetime import datetime, timezone
import os
import ssl
import time
import urllib.request


def quantity(value, memory=False):
    value = str(value)
    suffixes = {'Gi': 1024, 'Mi': 1, 'Ki': 1 / 1024} if memory else {'m': 1}
    for suffix, factor in suffixes.items():
        if value.endswith(suffix):
            return float(value[:-len(suffix)]) * factor
    return float(value) / (1024 * 1024) if memory else float(value) * 1000


def desired_replicas(sandboxes, claims, total=3, reserved=0, reservation=None,
                     cpu=3213, memory=12097):
    used_cpu, used_memory = 0, 0
    excluded = (reservation or {}).get("exclude", "")
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
            if name != excluded and item.get('spec', {}).get('operatingMode') != 'Suspended':
                for container in item.get('spec', {}).get('podTemplate', {}).get('spec', {}).get('containers', []):
                    requests = container.get('resources', {}).get('requests', {})
                    used_cpu += quantity(requests.get('cpu', 0))
                    used_memory += quantity(requests.get('memory', 0), memory=True)
    # A released disk still consumes quota until its claim disappears. Also
    # count suspended sessions, cold starts and any retained recovery claims.
    for claim in claims:
        name = claim['metadata']['name']
        if name.startswith('data-s-') and name[5:] not in warm:
            occupied.add(name[5:])
    if reservation:
        reserved += int(reservation.get('new_slot', False))
        used_cpu += reservation['cpu']
        used_memory += reservation['memory']
    available = min(total - reserved - len(occupied),
                    int((cpu - used_cpu) // 1000),
                    int((memory - used_memory) // 2560))
    return max(0, available)


def active_reservation(lease, now=None):
    spec = lease.get('spec', {})
    if not spec.get('holderIdentity'):
        return None
    renewed = datetime.fromisoformat(spec['renewTime'].replace('Z', '+00:00'))
    now = now or datetime.now(timezone.utc)
    if (now - renewed).total_seconds() >= spec.get('leaseDurationSeconds', 120):
        return None
    ann = lease['metadata'].get('annotations', {})
    return {'cpu': int(ann['browserjs.dev/capacity-cpu']),
            'memory': int(ann['browserjs.dev/capacity-memory']),
            'exclude': ann.get('browserjs.dev/capacity-exclude', ''),
            'new_slot': ann.get('browserjs.dev/capacity-new-slot') == 'true'}


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
            lease = api(f'/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases/session-capacity')
            wanted = desired_replicas(sandboxes, claims, reserved=int(os.getenv('RESERVED_SLOTS', '0')),
                                      reservation=active_reservation(lease))
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

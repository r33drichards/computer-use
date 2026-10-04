"""Keep one node's worth of global warm capacity across all DaemonSet replicas.

Every replica reconciles the same global inputs and uses resourceVersion CAS.
Do not multiply the warm budget by the node count: spares must not perpetuate
nodes provisioned for claimed sessions.
"""
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


def requests(containers):
    cpu, memory = 0, 0
    for container in containers:
        resources = container.get('resources', {}).get('requests', {})
        cpu += quantity(resources.get('cpu', 0))
        memory += quantity(resources.get('memory', 0), memory=True)
    return cpu, memory


def desired_replicas(sandboxes, reserved=0, reservation=None,
                     cpu=3213, memory=12097, pods=()):
    # Do not place a replacement beside a terminating pod on a surplus node.
    # Its affinity match must disappear before warm scheduling resumes.
    if any(pod['metadata'].get('deletionTimestamp') for pod in pods):
        return 0
    excluded = (reservation or {}).get("exclude", "")
    warm, held = set(), {}
    for item in sandboxes:
        name = item['metadata']['name']
        pooled = any(ref.get('kind') == 'SandboxWarmPool' and ref.get('name') == 's'
                     for ref in item['metadata'].get('ownerReferences', []))
        if pooled and not item['metadata'].get('deletionTimestamp'):
            warm.add(name)
        elif name != excluded and item.get('spec', {}).get('operatingMode') != 'Suspended':
            held[name] = requests(item.get('spec', {}).get('podTemplate', {}).get('spec', {}).get('containers', []))
    # A suspended or removed Sandbox can still have a live pod while its
    # controller drains it. Keep that compute occupied until the pod is gone.
    for pod in pods:
        name = next((ref['name'] for ref in pod['metadata'].get('ownerReferences', [])
                     if ref.get('kind') == 'Sandbox'), pod['metadata']['name'])
        if name in warm or name == excluded:
            continue
        actual = requests(pod.get('spec', {}).get('containers', []))
        desired = held.get(name, (0, 0))
        held[name] = tuple(max(a, b) for a, b in zip(actual, desired))
    used_cpu = reserved * 1000 + sum(value[0] for value in held.values())
    used_memory = reserved * 2560 + sum(value[1] for value in held.values())
    if reservation:
        used_cpu += reservation['cpu']
        used_memory += reservation['memory']
    return max(0, min(int((cpu - used_cpu) // 1000),
                      int((memory - used_memory) // 2560)))


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
            pods = api(f'/api/v1/namespaces/{namespace}/pods?labelSelector=app%3Dbrowserjs-session')['items']
            lease = api(f'/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases/session-capacity')
            wanted = desired_replicas(sandboxes, reserved=int(os.getenv('RESERVED_SLOTS', '0')),
                                      reservation=active_reservation(lease), pods=pods)
            pool = api(pool_path)
            if pool['spec'].get('replicas') != wanted:
                api(pool_path, {'metadata': {'resourceVersion': pool['metadata']['resourceVersion']},
                                'spec': {'replicas': wanted}})
                print(f'Warm sessions: {wanted}', flush=True)
        except Exception as error:
            # Fail closed: API errors never increase the pool. Retry from fresh state.
            print(f'Reconcile failed: {error}', flush=True)
        time.sleep(2)


if __name__ == '__main__':
    main()

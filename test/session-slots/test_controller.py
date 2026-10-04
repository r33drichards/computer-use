import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('slots', Path(__file__).resolve().parents[2] / 'deploy/gke/session-slots.py')
slots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(slots)


def sandbox(name, warm=False, deleting=False):
    return {'metadata': {'name': name, 'ownerReferences': [{'kind': 'SandboxWarmPool', 'name': 's'}] if warm else [], **({'deletionTimestamp': 'now'} if deleting else {})}}


def running(name, cpu='1', memory='2560Mi', warm=False):
    obj = sandbox(name, warm)
    obj['spec'] = {'operatingMode': 'Running', 'podTemplate': {'spec': {'containers': [{'resources': {'requests': {'cpu': cpu, 'memory': memory}}}]}}}
    return obj


class SlotsTest(unittest.TestCase):
    def test_two_claimed_one_warm(self):
        self.assertEqual(slots.desired_replicas([running('s-a'), running('s-b'), running('s-c', warm=True)]), 1)

    def test_claim_transfer_consumes_compute(self):
        self.assertEqual(slots.desired_replicas([running('s-a'), running('s-b'), running('s-c')]), 0)

    def test_suspended_sessions_do_not_limit_warm_pool(self):
        sleeping = [sandbox(f's-{i}') for i in range(4)]
        for item in sleeping:
            item['spec'] = {'operatingMode': 'Suspended'}
        self.assertEqual(slots.desired_replicas(sleeping), 3)

    def test_canary_reservation_and_empty_pool(self):
        self.assertEqual(slots.desired_replicas([]), 3)
        self.assertEqual(slots.desired_replicas([running('s-a'), running('s-b')], reserved=1), 0)

    def test_medium_and_large_yield_warm_compute(self):
        self.assertEqual(slots.desired_replicas([running('s-m', '1500m', '5632Mi')]), 1)
        self.assertEqual(slots.desired_replicas([running('s-l', '3', '11Gi')]), 0)
        self.assertEqual(slots.desired_replicas([running('s-a', '1', '2560Mi'), running('s-b', '1500m', '5632Mi')]), 0)
        self.assertEqual(slots.desired_replicas([], reservation={'cpu': 3000, 'memory': 11264, 'new_slot': True}), 0)
        self.assertEqual(slots.desired_replicas([], reservation={'cpu': 1500, 'memory': 5632, 'new_slot': True}), 1)

    def test_reservation_expires_after_backend_dies(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        lease = {'metadata': {'annotations': {'browserjs.dev/capacity-cpu': '1500', 'browserjs.dev/capacity-memory': '5632'}}, 'spec': {'holderIdentity': 'request', 'renewTime': now.isoformat(), 'leaseDurationSeconds': 120}}
        self.assertIsNotNone(slots.active_reservation(lease, now))
        self.assertIsNone(slots.active_reservation(lease, now + timedelta(seconds=120)))

    def test_multiple_nodes_do_not_multiply_warm_budget(self):
        items = [running(f's-{i}') for i in range(4)]
        for index, item in enumerate(items):
            item['status'] = {'nodeName': f'node-{index // 3}'}
        self.assertEqual(slots.desired_replicas(items), 0)

    def test_stopping_medium_keeps_compute_until_pod_is_gone(self):
        small = [running('s-a'), running('s-b')]
        stopped = sandbox('s-medium')
        stopped['spec'] = {'operatingMode': 'Suspended'}
        pod = {'metadata': {'name': 's-medium'}, 'spec': running('s-medium', '1500m', '5632Mi')['spec']['podTemplate']['spec']}
        self.assertEqual(slots.desired_replicas(small + [stopped], pods=[pod]), 0)
        self.assertEqual(slots.desired_replicas(small + [stopped]), 1)

    def test_terminating_pod_cannot_attract_a_warm_replacement(self):
        self.assertEqual(slots.desired_replicas([], pods=[{'metadata': {'name': 's-old', 'deletionTimestamp': 'now'}}]), 0)


if __name__ == '__main__':
    unittest.main()

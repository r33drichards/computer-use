import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('slots', Path(__file__).resolve().parents[2] / 'deploy/gke/session-slots.py')
slots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(slots)


def sandbox(name, warm=False, deleting=False):
    return {'metadata': {'name': name, 'ownerReferences': [{'kind': 'SandboxWarmPool', 'name': 's'}] if warm else [], **({'deletionTimestamp': 'now'} if deleting else {})}}


def pvc(name):
    return {'metadata': {'name': 'data-' + name}}


class SlotsTest(unittest.TestCase):
    def test_two_claimed_one_warm(self):
        self.assertEqual(slots.desired_replicas([sandbox('s-a'), sandbox('s-b'), sandbox('s-c', True)], [pvc('s-a'), pvc('s-b'), pvc('s-c')]), 1)

    def test_claim_transfer_consumes_a_slot(self):
        self.assertEqual(slots.desired_replicas([sandbox('s-a'), sandbox('s-b'), sandbox('s-c')], [pvc('s-a'), pvc('s-b'), pvc('s-c')]), 0)

    def test_release_waits_for_disk_deletion(self):
        self.assertEqual(slots.desired_replicas([sandbox('s-a'), sandbox('s-b')], [pvc('s-a'), pvc('s-b'), pvc('s-c')]), 0)
        self.assertEqual(slots.desired_replicas([sandbox('s-a'), sandbox('s-b')], [pvc('s-a'), pvc('s-b')]), 1)

    def test_deleting_warm_disk_is_not_replaced_early(self):
        self.assertEqual(slots.desired_replicas([sandbox('s-a', True, True)], [pvc('s-a')]), 2)

    def test_canary_reservation_and_empty_pool(self):
        self.assertEqual(slots.desired_replicas([], []), 3)
        self.assertEqual(slots.desired_replicas([sandbox('s-a'), sandbox('s-b')], [], reserved=1), 0)

    def test_medium_and_large_yield_warm_compute(self):
        def running(name, cpu, memory):
            obj = sandbox(name)
            obj['spec'] = {'operatingMode': 'Running', 'podTemplate': {'spec': {'containers': [{'resources': {'requests': {'cpu': cpu, 'memory': memory}}}]}}}
            return obj
        self.assertEqual(slots.desired_replicas([running('s-m', '1500m', '5632Mi')], []), 1)
        self.assertEqual(slots.desired_replicas([running('s-l', '3', '11Gi')], []), 0)
        self.assertEqual(slots.desired_replicas([running('s-a', '1', '2560Mi'), running('s-b', '1500m', '5632Mi')], []), 0)
        self.assertEqual(slots.desired_replicas([], [], reservation={'cpu': 3000, 'memory': 11264, 'new_slot': True}), 0)
        self.assertEqual(slots.desired_replicas([], [], reservation={'cpu': 1500, 'memory': 5632, 'new_slot': True}), 1)

    def test_reservation_expires_after_backend_dies(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        lease = {'metadata': {'annotations': {'browserjs.dev/capacity-cpu': '1500', 'browserjs.dev/capacity-memory': '5632'}}, 'spec': {'holderIdentity': 'request', 'renewTime': now.isoformat(), 'leaseDurationSeconds': 120}}
        self.assertIsNotNone(slots.active_reservation(lease, now))
        self.assertIsNone(slots.active_reservation(lease, now + timedelta(seconds=120)))

    def test_over_budget_does_not_grow(self):
        self.assertEqual(slots.desired_replicas([sandbox(f's-{i}') for i in range(4)], []), 0)


if __name__ == '__main__':
    unittest.main()

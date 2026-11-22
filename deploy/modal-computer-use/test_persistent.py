import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from persistent import BUSY, CONTROL, Controller, DesktopRecoveryError


class CheckpointTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.box = SimpleNamespace(
            object_id="current", terminate=SimpleNamespace(aio=AsyncMock())
        )
        self.ctl = Controller("test", None, None, None, idle=0)
        self.row = {
            "active": "current",
            "disk": "old",
            "last": 0,
            "fresh": False,
            "slot": "slot",
        }
        self.ctl.active = AsyncMock(return_value=self.box)
        self.ctl.snapshot = AsyncMock(return_value=SimpleNamespace(object_id="new"))

        async def record():
            return self.row.copy()

        async def put(_, row):
            self.row = row.copy()

        self.ctl.state = SimpleNamespace(put=SimpleNamespace(aio=put))
        self.ctl.record = record

    async def test_timeout_recovers_without_replacing_or_terminating(self):
        original = TimeoutError("snapshot timed out")
        self.ctl.snapshot.side_effect = original
        with patch(
            "persistent.command", new_callable=AsyncMock, return_value=""
        ) as command:
            with self.assertRaises(TimeoutError) as ctx:
                await self.ctl.checkpoint_if_idle()
            self.assertIs(ctx.exception, original)
            self.assertEqual(
                [(c.args[1:]) for c in command.await_args_list],
                [(BUSY,), (CONTROL, "drained", "slot"), (CONTROL, "ready", "slot")],
            )
            self.assertEqual(self.row["disk"], "old")
            self.assertEqual(self.row["active"], "current")
            self.assertFalse(self.row["checkpoint_pending"])
            self.assertFalse(await self.ctl.checkpoint_if_idle())
        self.box.terminate.aio.assert_not_awaited()

    async def test_failed_recovery_preserves_cause_and_fences_stale_restore(self):
        original = TimeoutError("snapshot timed out")
        self.ctl.snapshot.side_effect = original
        with patch(
            "persistent.command",
            new_callable=AsyncMock,
            side_effect=["", "", RuntimeError("not ready")],
        ):
            with self.assertRaises(DesktopRecoveryError) as ctx:
                await self.ctl.checkpoint_if_idle()
        self.assertIs(ctx.exception.__cause__, original)
        self.assertTrue(self.row["checkpoint_pending"])
        self.assertEqual(self.row["disk"], "old")
        self.box.terminate.aio.assert_not_awaited()
        self.ctl.active.return_value = None
        self.row["checkpoint_retry_after"] = 0
        self.assertFalse(await self.ctl.checkpoint_if_idle())
        self.assertEqual(self.row["active"], "current")
        with self.assertRaisesRegex(DesktopRecoveryError, "refusing stale restore"):
            await self.ctl.ensure()

    async def test_interrupted_seal_recovers_before_retrying(self):
        self.row["checkpoint_pending"] = True
        with patch("persistent.command", new_callable=AsyncMock) as command:
            self.assertFalse(await self.ctl.checkpoint_if_idle())
            command.assert_awaited_once_with(self.box, CONTROL, "ready", "slot")
        self.ctl.snapshot.assert_not_awaited()
        self.assertFalse(self.row["checkpoint_pending"])

    async def test_success_persists_new_disk_before_termination(self):
        async def retire():
            self.assertEqual(self.row["disk"], "new")
            self.assertFalse(self.row["checkpoint_pending"])

        self.box.terminate.aio.side_effect = retire
        with patch("persistent.command", new_callable=AsyncMock, return_value=""):
            self.assertTrue(await self.ctl.checkpoint_if_idle())
        self.assertEqual(self.row["disk"], "new")
        self.assertIsNone(self.row["active"])
        self.box.terminate.aio.assert_awaited_once()

"""A killed worker must be reaped before its event loop closes."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ringer


class WorkerShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_awaits_every_worker_after_kill(self):
        events = []
        worker = SimpleNamespace(pid=1234, returncode=None)
        exited = SimpleNamespace(pid=1235, returncode=0)
        async def reap_worker():
            events.append("reaped")
            worker.returncode = -9
        worker.wait = AsyncMock(side_effect=reap_worker)
        exited.wait = AsyncMock(return_value=0)
        runner = SimpleNamespace(active_processes={1234: worker, 1235: exited})
        with patch.object(ringer, "terminate_process_group", side_effect=lambda p: events.append("term")), \
             patch.object(ringer, "kill_process_group", side_effect=lambda p: events.append("kill")), \
             patch.object(ringer.asyncio, "sleep", new=AsyncMock()):
            await ringer.RingerRunner.kill_all_workers(runner)
        self.assertEqual(events, ["term", "kill", "reaped"])
        worker.wait.assert_awaited_once()
        exited.wait.assert_awaited_once()
        self.assertEqual(runner.active_processes, {})

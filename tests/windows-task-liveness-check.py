"""Windows-only liveness regression against this test's own synthetic process.

No accounts, Codex, documents, microphones or USB are accessed. The production
probe must not use Windows os.kill(pid, 0), which can terminate a process.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from agent_tasks import TaskStore


@unittest.skipUnless(os.name == "nt", "Requires Windows process API; never count a Mac/Linux skip as Windows validation")
class WindowsTaskLivenessChecks(unittest.TestCase):
    def test_live_worker_probe_does_not_terminate_the_worker(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            for _ in range(50):
                self.assertTrue(TaskStore.worker_alive({"workerPid": child.pid}))
            time.sleep(0.1)
            self.assertIsNone(child.poll(), "Checking a task killed its live worker")
            child.terminate()
            child.wait(timeout=5)
            self.assertFalse(TaskStore.worker_alive({"workerPid": child.pid}), "Exited worker still reported as live")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()

    def test_missing_or_invalid_worker_identity_is_not_alive(self):
        for value in (None, -1, 0, "123", {}):
            with self.subTest(value=value):
                self.assertFalse(TaskStore.worker_alive({"workerPid": value}))


if __name__ == "__main__":
    unittest.main(verbosity=2)

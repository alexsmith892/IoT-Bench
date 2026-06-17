import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.runner import build_lock


class BuildLockTests(unittest.TestCase):
    def test_noop_when_env_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("IOTBENCH_BUILD_LOCK", None)
            with build_lock():
                pass  # must not raise or create anything

    def test_acquires_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "build.lock"
            with patch.dict(os.environ, {"IOTBENCH_BUILD_LOCK": str(lock)}):
                with build_lock():
                    self.assertTrue(lock.exists(), "lock should be held inside the context")
                self.assertFalse(lock.exists(), "lock should be released on exit")
                # Re-acquirable after release.
                with build_lock():
                    self.assertTrue(lock.exists())

    def test_steals_stale_lock_instead_of_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "build.lock"
            lock.write_text("99999 0\n", encoding="utf-8")
            old = 1.0  # far in the past
            os.utime(lock, (old, old))
            env = {"IOTBENCH_BUILD_LOCK": str(lock), "IOTBENCH_BUILD_LOCK_TIMEOUT_S": "1"}
            with patch.dict(os.environ, env):
                with build_lock():
                    self.assertTrue(lock.exists())
                self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()

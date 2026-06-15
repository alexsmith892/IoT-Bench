"""Opt-in live Renode/Zephyr smoke tests (build + headless simulate + judge).

Gated like the Wokwi optional suite: set ``RUN_RENODE_INTEGRATION=1`` and have
Renode + west + a Zephyr workspace available. CI never runs these (no Renode or
Zephyr SDK on the runner); they are the reproducible local proof that the
build -> Renode -> capture -> validate loop reaches a meaningful verdict, not
just that Renode launched.

Two guarantees beyond "it ran":
- reference firmware reaches BC with non-empty captured evidence (a non-trivial
  VCD / serial log), so an empty-capture regression like the historical easyDMA
  UART bug cannot masquerade as a pass; and
- the run is deterministic in virtual time (two runs -> byte-identical VCD).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from bench.cli import run_single_task
from bench.config import load_task
from bench.renode import renode_executable, west_executable, zephyr_workspace
from bench.results import RESULT_BC
from bench.runner import generate_case

REPO_ROOT = Path(__file__).resolve().parents[2]


def _renode_available() -> bool:
    exe = renode_executable("renode")
    return bool(shutil.which("renode")) or (exe != "renode" and Path(exe).exists())


def _west_available() -> bool:
    exe = west_executable("west")
    return bool(shutil.which("west")) or (exe != "west" and Path(exe).exists())


def _workspace_available() -> bool:
    return (zephyr_workspace() / "zephyr").exists()


# Reference tasks spanning the evidence types the backend must get right:
# waveform/VCD, serial counting, analog (SAADC), I2C sensor, LCD-over-VCD.
BC_TASKS = [
    ("blink_led_1hz", "level1"),
    ("button_status_count", "level1"),
    ("tmp36_read", "level1"),
    ("mpu6050_read_i2c", "level2"),
    ("lcd1602_display_hello_world", "level2"),
]


@unittest.skipUnless(
    os.environ.get("RUN_RENODE_INTEGRATION") == "1",
    "set RUN_RENODE_INTEGRATION=1 to run live Renode/Zephyr smoke tests",
)
@unittest.skipUnless(_renode_available(), "renode is not available")
@unittest.skipUnless(_west_available(), "west is not available")
@unittest.skipUnless(_workspace_available(), "Zephyr workspace not found (set ZEPHYR_WORKSPACE)")
class OptionalRenodeOutcomeSmokeTests(unittest.TestCase):
    def test_reference_tasks_reach_bc_with_evidence(self) -> None:
        for task_id, level in BC_TASKS:
            with self.subTest(task=task_id):
                payload, paths = self._run_temp_case(task_id, level=level)
                self.assertEqual(
                    RESULT_BC,
                    payload.get("result"),
                    f"{task_id}: expected BC, got {payload.get('result')} "
                    f"({payload.get('reason')})",
                )
                self._assert_capture_non_trivial(task_id, paths)

    def test_blink_is_deterministic_across_runs(self) -> None:
        first = self._vcd_digest("blink_led_1hz", "level1")
        second = self._vcd_digest("blink_led_1hz", "level1")
        self.assertEqual(
            first,
            second,
            "two Renode runs of blink_led_1hz produced different VCDs; "
            "virtual-time determinism is broken",
        )

    # -- helpers --------------------------------------------------------------

    def _run_temp_case(self, task_id: str, *, level: str):
        tmp = tempfile.mkdtemp(prefix="iotbench-renode-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root = Path(tmp)
        task = load_task(task_id, level=level)
        paths = generate_case(task, root=root)
        payload = run_single_task(
            task,
            case_dir=paths.case_dir,
            sketch_override=None,
            use_existing_artifacts=False,
            regenerate=False,
            simulation_time_ms=None,
            arduino_cli="arduino-cli",
            wokwi_cli="wokwi-cli",
            west="west",
            renode_cli="renode",
            archived_vcd=None,
        )
        return payload, paths

    def _assert_capture_non_trivial(self, task_id: str, paths) -> None:
        # At least one of VCD / serial must carry real firmware output. A VCD
        # with no value-change lines or a zero-byte serial log is an empty
        # capture, not a pass.
        evidence = False
        if paths.vcd and paths.vcd.exists():
            lines = paths.vcd.read_text(encoding="utf-8", errors="replace").splitlines()
            value_changes = [ln for ln in lines if ln and ln[0] in "01#"]
            if len(value_changes) > 2:
                evidence = True
        if paths.serial_log and paths.serial_log.exists():
            if paths.serial_log.stat().st_size > 0:
                evidence = True
        self.assertTrue(
            evidence,
            f"{task_id}: simulation produced no non-trivial VCD or serial evidence",
        )

    def _vcd_digest(self, task_id: str, level: str) -> str:
        _, paths = self._run_temp_case(task_id, level=level)
        self.assertIsNotNone(paths.vcd, f"{task_id} has no VCD path")
        self.assertTrue(paths.vcd.exists(), f"{task_id} produced no VCD")
        return hashlib.sha256(paths.vcd.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()

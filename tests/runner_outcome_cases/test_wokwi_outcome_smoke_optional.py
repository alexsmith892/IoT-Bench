from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from bench.cli import run_single_task
from bench.config import iter_tasks, load_task
from bench.results import RESULT_BC, RESULT_BF, RESULT_CF
from bench.runner import generate_case

from tests.runner_outcome_cases.helpers import FIXTURES, assert_payload_result, task_fixture


@unittest.skipUnless(
    os.environ.get("RUN_WOKWI_INTEGRATION") == "1",
    "set RUN_WOKWI_INTEGRATION=1 to run Wokwi outcome smoke tests",
)
@unittest.skipUnless(shutil.which("arduino-cli"), "arduino-cli is not on PATH")
@unittest.skipUnless(shutil.which("wokwi-cli"), "wokwi-cli is not on PATH")
@unittest.skipUnless(os.environ.get("WOKWI_CLI_TOKEN"), "WOKWI_CLI_TOKEN is not set")
class OptionalWokwiOutcomeSmokeTests(unittest.TestCase):
    def test_reference_waveform_task_reaches_bc(self):
        payload = self.run_temp_case("blink_led_1hz")
        assert_payload_result(self, payload, RESULT_BC)

    def test_reference_serial_task_reaches_bc(self):
        payload = self.run_temp_case("button_status_count")
        assert_payload_result(self, payload, RESULT_BC)

    def test_compilable_wrong_behavior_reaches_bf(self):
        payload = self.run_temp_case(
            "blink_led_1hz",
            sketch_override=task_fixture("level1", "blink_led_1hz", "bad"),
        )
        assert_payload_result(self, payload, RESULT_BF)

    def test_uncompilable_submission_reaches_cf(self):
        payload = self.run_temp_case(
            "blink_led_1hz",
            sketch_override=FIXTURES / "cf" / "uncompilable.ino",
        )
        assert_payload_result(self, payload, RESULT_CF)

    def run_temp_case(self, task_id: str, *, level: str = "level1", sketch_override: Path | None = None) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task(task_id, level=level)
            paths = generate_case(task, root=root)
            return run_single_task(
                task,
                case_dir=paths.case_dir,
                sketch_override=sketch_override,
                use_existing_artifacts=False,
                regenerate=False,
                simulation_time_ms=None,
                arduino_cli="arduino-cli",
                wokwi_cli="wokwi-cli",
                archived_vcd=None,
            )


@unittest.skipUnless(
    os.environ.get("RUN_WOKWI_TASK_CORPUS") == "1",
    "set RUN_WOKWI_TASK_CORPUS=1 to run every per-task good/bad firmware fixture",
)
@unittest.skipUnless(shutil.which("arduino-cli"), "arduino-cli is not on PATH")
@unittest.skipUnless(shutil.which("wokwi-cli"), "wokwi-cli is not on PATH")
@unittest.skipUnless(os.environ.get("WOKWI_CLI_TOKEN"), "WOKWI_CLI_TOKEN is not set")
class OptionalFullTaskCorpusWokwiTests(unittest.TestCase):
    def test_all_good_task_fixtures_reach_bc(self):
        for level in ("level1", "level2", "level3"):
            for task in iter_tasks(platform="arduino_mega", level=level):
                if not task.is_supported:
                    continue
                with self.subTest(task=task.task_id):
                    payload = run_task_fixture(task.task_id, level, "good")
                    assert_payload_result(self, payload, RESULT_BC)

    def test_all_bad_task_fixtures_reach_bf(self):
        for level in ("level1", "level2", "level3"):
            for task in iter_tasks(platform="arduino_mega", level=level):
                if not task.is_supported:
                    continue
                with self.subTest(task=task.task_id):
                    payload = run_task_fixture(task.task_id, level, "bad")
                    assert_payload_result(self, payload, RESULT_BF)


def run_task_fixture(task_id: str, level: str, outcome: str) -> dict:
    task = load_task(task_id, level=level)
    with tempfile.TemporaryDirectory() as tmp:
        paths = generate_case(task, root=Path(tmp))
        return run_single_task(
            task,
            case_dir=paths.case_dir,
            sketch_override=task_fixture(level, task_id, outcome),
            use_existing_artifacts=False,
            regenerate=False,
            simulation_time_ms=None,
            arduino_cli="arduino-cli",
            wokwi_cli="wokwi-cli",
            archived_vcd=None,
        )


if __name__ == "__main__":
    unittest.main()

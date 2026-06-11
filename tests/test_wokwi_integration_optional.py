import json
import os
import shutil
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

from bench.config import iter_tasks


ROOT = Path(__file__).resolve().parents[1]


def expected_summary(level: str) -> dict[str, int]:
    """Supported tasks must reach BC; manual/unsupported tasks are reported as IF."""
    counts: Counter[str] = Counter()
    for task in iter_tasks(platform="arduino_mega", level=level):
        counts["BC" if task.is_supported else "IF"] += 1
    return dict(counts)


def run_level(level: str, timeout_s: int) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "bench.cli", "run", "--platform", "arduino_mega",
         "--level", level, "--regenerate"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        check=False, timeout=timeout_s,
    )
    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    return json.loads(completed.stdout)


@unittest.skipUnless(
    os.environ.get("RUN_WOKWI_INTEGRATION") == "1",
    "set RUN_WOKWI_INTEGRATION=1 to run Wokwi integration tests",
)
@unittest.skipUnless(shutil.which("arduino-cli"), "arduino-cli is not on PATH")
@unittest.skipUnless(shutil.which("wokwi-cli"), "wokwi-cli is not on PATH")
@unittest.skipUnless(os.environ.get("WOKWI_CLI_TOKEN"), "WOKWI_CLI_TOKEN is not set")
class OptionalWokwiIntegrationTests(unittest.TestCase):
    def test_all_arduino_mega_level1_tasks_run_end_to_end(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "bench.cli",
                "run",
                "--platform",
                "arduino_mega",
                "--level",
                "level1",
                "--regenerate",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=90,
        )

        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["summary"], {"BC": 11}, payload)

    def test_all_arduino_mega_level2_tasks_reach_expected_results(self):
        payload = run_level("level2", timeout_s=900)
        self.assertEqual(payload["summary"], expected_summary("level2"), payload)
        self._assert_no_unexpected_failures(payload)

    def test_all_arduino_mega_level3_tasks_reach_expected_results(self):
        payload = run_level("level3", timeout_s=900)
        self.assertEqual(payload["summary"], expected_summary("level3"), payload)
        self._assert_no_unexpected_failures(payload)

    def _assert_no_unexpected_failures(self, payload: dict) -> None:
        # No supported task should land in BF/CF; surface the offenders if any do.
        bad = [r for r in payload["results"] if r["result"] in {"BF", "CF"}]
        self.assertEqual(
            bad, [], "supported tasks must reach BC: " + json.dumps(bad, indent=2)
        )


@unittest.skipUnless(
    os.environ.get("RUN_WOKWI_INTEGRATION") == "1",
    "set RUN_WOKWI_INTEGRATION=1 to run Wokwi integration tests",
)
@unittest.skipUnless(shutil.which("idf.py"), "idf.py is not on PATH")
@unittest.skipUnless(shutil.which("wokwi-cli"), "wokwi-cli is not on PATH")
@unittest.skipUnless(os.environ.get("WOKWI_CLI_TOKEN"), "WOKWI_CLI_TOKEN is not set")
class OptionalEsp32S3EspIdfIntegrationTests(unittest.TestCase):
    def test_representative_espidf_level1_tasks_run_end_to_end(self):
        for task_id in ("blink_led_1hz", "button_status_count", "breathing_led", "tmp36_read"):
            with self.subTest(task=task_id):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "bench.cli",
                        "run",
                        "--platform",
                        "esp32s3_espidf",
                        "--level",
                        "level1",
                        "--task",
                        task_id,
                        "--regenerate",
                    ],
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=240,
                )

                self.assertEqual(
                    completed.returncode,
                    0,
                    msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                )
                payload = json.loads(completed.stdout)
                self.assertEqual(payload["result"], "BC", payload)


if __name__ == "__main__":
    unittest.main()

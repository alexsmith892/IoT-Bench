import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    unittest.main()

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bench.leaderboard.cli import main


class LeaderboardPlanCliTests(unittest.TestCase):
    def test_plan_prints_counts(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "plan",
                    "--benchmark",
                    "iot_skillsbench_v1",
                    "--platform",
                    "arduino_mega",
                    "--levels",
                    "1",
                    "--skill-modes",
                    "none,llm_generated,human_expert",
                    "--tasks",
                    "blink_led_1hz",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["tasks"], 1)
        self.assertEqual(payload["generation_count"], 3)

    def test_run_dry_run_spends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dry"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "run",
                        "--benchmark",
                        "iot_skillsbench_v1",
                        "--platform",
                        "arduino_mega",
                        "--levels",
                        "1",
                        "--skill-modes",
                        "none",
                        "--tasks",
                        "blink_led_1hz",
                        "--model",
                        "fixture:reference",
                        "--out",
                        str(out),
                        "--dry-run",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["dry_run"])
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()


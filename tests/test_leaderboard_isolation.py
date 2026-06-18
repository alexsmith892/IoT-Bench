import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bench.config import load_task
from bench.leaderboard.evaluate import evaluate_source


class LeaderboardIsolationTests(unittest.TestCase):
    def test_evaluate_uses_isolated_case_dir(self):
        task = load_task("blink_led_1hz")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "blink_led_1hz.ino"
            source.write_text("void setup(){}\nvoid loop(){}\n", encoding="utf-8")
            seen = {}

            def fake_generate_case(task_arg, *, root):
                case_dir = root / "cases" / "blink-1hz-wokwi-mega"
                case_dir.mkdir(parents=True)
                return SimpleNamespace(case_dir=case_dir)

            def fake_timed_run_single_task(task_arg, **kwargs):
                seen["case_dir"] = kwargs["case_dir"]
                seen["sketch_override"] = kwargs["sketch_override"]
                return {
                    "attempt": kwargs["attempt_index"],
                    "result": {
                        "result": "BC",
                        "classification": "PASS",
                        "failure_stage": None,
                        "failure_source": None,
                        "reason": "ok",
                        "metrics": {},
                    },
                }

            with patch("bench.leaderboard.evaluate.generate_case", side_effect=fake_generate_case), patch(
                "bench.leaderboard.evaluate.timed_run_single_task", side_effect=fake_timed_run_single_task
            ):
                result = evaluate_source(
                    task,
                    source_path=source,
                    run_dir=root / "run",
                    attempt_slug="blink.none.1",
                    if_retries=1,
                    simulation_time_ms=None,
                )

            self.assertEqual(result["final_result"]["result"], "BC")
            self.assertIn(str(root / "run" / "workspace"), str(seen["case_dir"]))
            self.assertNotIn(str(Path.cwd() / "cases"), str(seen["case_dir"]))
            self.assertEqual(seen["sketch_override"], source)


if __name__ == "__main__":
    unittest.main()


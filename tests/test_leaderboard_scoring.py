import json
import tempfile
import unittest
from pathlib import Path

from bench.leaderboard.reports import summarize_attempts, write_reports


def row(task, mode, rep, result, *, stage=None, cost=1.0, tokens=100):
    return {
        "run_name": "r",
        "model": "fixture:reference",
        "provider": "fixture",
        "platform": "arduino_mega",
        "level": "level1",
        "canonical_id": task,
        "local_task_id": task,
        "skill_mode": mode,
        "skills_used": [],
        "rep_index": rep,
        "temperature": 0.2,
        "top_p": 1.0,
        "max_tokens": 4096,
        "seed": None,
        "base_input_tokens": None,
        "skill_input_tokens": None,
        "output_tokens": None,
        "total_tokens": tokens,
        "cost_usd": cost,
        "pricing_table_version": "test",
        "num_model_calls": 1,
        "latency_s": 0.1,
        "generation_retries": 0,
        "if_retries_used": 0,
        "result": result,
        "classification": "PASS" if result == "BC" else "FAIL",
        "failure_stage": stage,
        "failure_source": None,
        "reason": "x",
        "metrics": {},
        "prompt_path": "prompts/x.md",
        "response_path": "responses/x.json",
        "source_path": "sources/x/x.ino",
        "publishable": True,
    }


class LeaderboardScoringTests(unittest.TestCase):
    def test_if_excluded_from_scored_rate_and_pass_at_k(self):
        attempts = [
            row("a", "none", 1, "IF", stage="simulate"),
            row("a", "none", 2, "BC"),
            row("b", "none", 1, "CF", stage="compile"),
            row("b", "none", 2, "BF", stage="behavior"),
            row("a", "human_expert", 1, "BC", cost=2.0, tokens=200),
            row("b", "human_expert", 1, "BC", cost=2.0, tokens=200),
        ]

        summary = summarize_attempts(attempts)
        none = next(row for row in summary["headline"] if row["skill_mode"] == "none")
        human = next(row for row in summary["headline"] if row["skill_mode"] == "human_expert")
        lift = summary["skill_lift"][0]

        self.assertEqual(none["if_rate"], 0.25)
        self.assertEqual(none["pass_rate_scored"], round(1 / 3, 6))
        self.assertEqual(none["pass_at_k"], 0.5)
        self.assertEqual(human["pass_at_1"], 1.0)
        self.assertEqual(lift["delta_pass_at_1"], 0.75)

    def test_write_reports_outputs_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "attempts.jsonl").write_text(
                json.dumps(row("a", "none", 1, "BC")) + "\n",
                encoding="utf-8",
            )

            reports = write_reports(run_dir)

            for path in reports.values():
                self.assertTrue(Path(path).exists(), path)
            self.assertIn("leaderboard.md", reports["leaderboard_md"])


if __name__ == "__main__":
    unittest.main()


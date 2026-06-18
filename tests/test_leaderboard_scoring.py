import json
import tempfile
import unittest
from pathlib import Path

from bench.leaderboard.reports import summarize_attempts, write_reports


def row(task, mode, rep, result, *, stage=None, cost=1.0, tokens=100, model="fixture:reference", level="level1", skill_tokens=None):
    return {
        "run_name": "r",
        "model": model,
        "provider": model.split(":", 1)[0],
        "platform": "arduino_mega",
        "level": level,
        "canonical_id": task,
        "local_task_id": task,
        "skill_mode": mode,
        "skills_used": [],
        "rep_index": rep,
        "temperature": 0.2,
        "top_p": 1.0,
        "max_tokens": 4096,
        "seed": None,
        "input_tokens": tokens,
        "base_input_tokens": None,
        "skill_input_tokens": skill_tokens,
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
        "extraction": {},
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
        self.assertIn("bc_pct", none)

    def test_coverage_uses_experiment_score_eligible_denominator(self):
        attempts = [
            row("a", "none", 1, "BC"),
            row("b", "none", 1, "IF", stage="simulate"),
        ]
        experiment = {
            "reps": 1,
            "selected_tasks": [
                {"local_task_id": "a", "platform": "arduino_mega", "level": "level1", "score_eligible": True},
                {"local_task_id": "b", "platform": "arduino_mega", "level": "level1", "score_eligible": True},
                {"local_task_id": "c", "platform": "arduino_mega", "level": "level1", "score_eligible": True},
            ],
        }

        summary = summarize_attempts(attempts, experiment=experiment)
        none = summary["headline"][0]

        self.assertEqual(none["coverage_denominator"], 3)
        self.assertEqual(none["coverage_rate"], round(1 / 3, 6))

    def test_write_reports_outputs_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "attempts.jsonl").write_text(
                json.dumps(row("a", "none", 1, "BC")) + "\n",
                encoding="utf-8",
            )
            (run_dir / "experiment.json").write_text(
                json.dumps(
                    {
                        "reps": 1,
                        "selected_tasks": [
                            {
                                "local_task_id": "a",
                                "platform": "arduino_mega",
                                "level": "level1",
                                "score_eligible": True,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            reports = write_reports(run_dir)

            for path in reports.values():
                self.assertTrue(Path(path).exists(), path)
            self.assertIn("leaderboard.md", reports["leaderboard_md"])

    def test_multi_model_level_rep_aggregation_and_skill_token_lift(self):
        attempts = [
            row("a", "none", 1, "BF", model="openai:m1", level="level1", tokens=100),
            row("a", "none", 2, "BC", model="openai:m1", level="level1", tokens=100),
            row("b", "none", 1, "BC", model="openai:m1", level="level2", tokens=100),
            row("a", "human_expert", 1, "BC", model="openai:m1", level="level1", tokens=120, skill_tokens=20),
            row("a", "none", 1, "BC", model="openai:m2", level="level1", tokens=80),
        ]

        summary = summarize_attempts(attempts)
        self.assertEqual(len(summary["headline"]), 3)
        m1_none = next(row for row in summary["headline"] if row["model"] == "openai:m1" and row["skill_mode"] == "none")
        self.assertEqual(m1_none["attempted"], 3)
        self.assertEqual(m1_none["pass_at_k"], 1.0)
        lift = next(row for row in summary["skill_lift"] if row["model"] == "openai:m1")
        self.assertIsNotNone(lift["lift_per_1k_skill_tokens"])

    def test_report_publishability_high_if_rate(self):
        summary = summarize_attempts([row("a", "none", 1, "IF", stage="generation")], if_threshold=0.05)

        self.assertEqual(summary["metadata"]["publishability"], "high_if_rate")
        self.assertEqual(summary["metadata"]["if_threshold"], 0.05)

    def test_report_regeneration_is_deterministic_from_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "attempts.jsonl").write_text(
                json.dumps(row("a", "none", 1, "BC")) + "\n"
                + json.dumps(row("b", "none", 1, "CF", stage="format")) + "\n",
                encoding="utf-8",
            )
            (run_dir / "experiment.json").write_text(
                json.dumps(
                    {
                        "publishability": "publishable",
                        "reps": 1,
                        "selected_tasks": [
                            {
                                "local_task_id": "a",
                                "platform": "arduino_mega",
                                "level": "level1",
                                "score_eligible": True,
                            },
                            {
                                "local_task_id": "b",
                                "platform": "arduino_mega",
                                "level": "level1",
                                "score_eligible": True,
                            },
                        ],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            first = write_reports(run_dir, if_threshold=0.05)
            first_payload = {name: Path(path).read_text(encoding="utf-8") for name, path in first.items()}
            second = write_reports(run_dir, if_threshold=0.05)
            second_payload = {name: Path(path).read_text(encoding="utf-8") for name, path in second.items()}

            self.assertEqual(first_payload, second_payload)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from bench.config import ConfigError
from bench.leaderboard.manifest import load_manifest, resolve_plan
from bench.leaderboard.skills import verify_skill_lock


class LeaderboardManifestTests(unittest.TestCase):
    def test_plan_counts_arduino_mvp_generations(self):
        plan = resolve_plan(
            "iot_skillsbench_v1",
            platform="arduino_mega",
            levels="1,2,3",
            skill_modes="none,llm_generated,human_expert",
        )

        self.assertEqual(plan.counts["selected"], 41)
        self.assertEqual(plan.counts["score_eligible"], 41)
        self.assertEqual(plan.generation_count, 123)
        self.assertTrue(plan.publishable)

    def test_unknown_task_fails(self):
        with self.assertRaises(ConfigError):
            resolve_plan(
                "iot_skillsbench_v1",
                platform="arduino_mega",
                levels="1",
                task_ids="not_a_task",
            )

    def test_unpublishable_score_task_fails_without_override(self):
        with patch("bench.leaderboard.manifest._evidence_by_task", return_value={}):
            with self.assertRaises(ConfigError):
                resolve_plan(
                    "iot_skillsbench_v1",
                    platform="arduino_mega",
                    levels="1",
                    task_ids="blink_led_1hz",
                )

            plan = resolve_plan(
                "iot_skillsbench_v1",
                platform="arduino_mega",
                levels="1",
                task_ids="blink_led_1hz",
                allow_unpublishable=True,
            )
            self.assertFalse(plan.publishable)

    def test_manifest_rejects_oracle_like_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench = root / "benchmarks" / "bad"
            bench.mkdir(parents=True)
            (bench / "manifest.yaml").write_text(
                yaml.safe_dump(
                    {
                        "benchmark_id": "bad",
                        "schema_version": 1,
                        "skill_modes": {"none": {"use_skills": False}},
                        "tasks": [{"canonical_id": "x", "validator": {"params": {}}}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_manifest("bad", root=root)

    def test_skill_lock_hashes_match(self):
        locked = verify_skill_lock(Path("benchmarks") / "iot_skillsbench_v1")
        self.assertIn("skillpacks/human_expert/arduino-framework.md", locked)


if __name__ == "__main__":
    unittest.main()


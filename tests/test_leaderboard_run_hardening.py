import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.config import ConfigError, load_task
from bench.leaderboard.manifest import resolve_plan
from bench.leaderboard.providers import generate_response
from bench.leaderboard.run import run_experiment


def attempt_row(task_id="blink_led_1hz", mode="none", rep=1):
    return {
        "run_name": "run",
        "model": "fixture:reference",
        "provider": "fixture",
        "platform": "arduino_mega",
        "level": "level1",
        "canonical_id": task_id,
        "local_task_id": task_id,
        "skill_mode": mode,
        "skills_used": [],
        "rep_index": rep,
        "temperature": 0.2,
        "top_p": 1.0,
        "max_tokens": 4096,
        "seed": None,
        "base_input_tokens": None,
        "skill_input_tokens": None,
        "base_prompt_chars": 10,
        "skill_prompt_chars": 0,
        "output_tokens": None,
        "total_tokens": None,
        "cost_usd": None,
        "pricing_table_version": "test",
        "num_model_calls": 1,
        "latency_s": 0.1,
        "generation_retries": 0,
        "if_retries_used": 0,
        "result": "BC",
        "classification": "PASS",
        "failure_stage": None,
        "failure_source": None,
        "reason": "ok",
        "metrics": {},
        "prompt_path": "prompts/a.md",
        "response_path": "responses/a.json",
        "source_path": "sources/a/a.ino",
        "publishable": True,
    }


class LeaderboardRunHardeningTests(unittest.TestCase):
    def _plan(self):
        return resolve_plan(
            "iot_skillsbench_v1",
            platform="arduino_mega",
            levels="1",
            skill_modes="none",
            task_ids="blink_led_1hz",
            reps=1,
        )

    def test_existing_run_dir_requires_resume_or_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            out.mkdir()
            (out / "marker.txt").write_text("x", encoding="utf-8")

            with self.assertRaises(ConfigError):
                run_experiment(
                    self._plan(),
                    model="fixture:reference",
                    out=out,
                    dry_run=False,
                    confirm_spend=True,
                    resume=False,
                    force=False,
                    max_generations=None,
                    reps=1,
                    temperature=0.2,
                    top_p=1.0,
                    max_tokens=4096,
                    seed=None,
                    if_retries=0,
                    api_base=None,
                    api_key_env="OPENAI_API_KEY",
                    simulation_time_ms=None,
                    allow_tool_version_mismatch=False,
                    allow_unpublishable=False,
                    cli_args={"out": out},
                )

    def test_force_allows_existing_dir_and_records_metadata(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "bench.leaderboard.run._run_one", return_value=attempt_row()
        ), patch("bench.leaderboard.run.current_tool_versions", return_value={"ok": "yes"}):
            out = Path(tmp) / "run"
            out.mkdir()
            (out / "marker.txt").write_text("x", encoding="utf-8")

            result = run_experiment(
                self._plan(),
                model="fixture:reference",
                out=out,
                dry_run=False,
                confirm_spend=True,
                resume=False,
                force=True,
                max_generations=None,
                reps=1,
                temperature=0.2,
                top_p=1.0,
                max_tokens=4096,
                seed=None,
                if_retries=0,
                api_base=None,
                api_key_env="OPENAI_API_KEY",
                simulation_time_ms=None,
                allow_tool_version_mismatch=False,
                allow_unpublishable=False,
                cli_args={"out": out, "force": True},
            )

            experiment = json.loads((out / "experiment.json").read_text(encoding="utf-8"))
            self.assertEqual(result["attempts_written"], 1)
            self.assertEqual(experiment["build_kinds"], ["arduino"])
            self.assertEqual(experiment["tool_versions"]["arduino"], {"ok": "yes"})
            self.assertEqual(experiment["selected_tasks"][0]["local_task_id"], "blink_led_1hz")
            self.assertEqual(experiment["cli_args"]["out"], str(out))

    def test_resume_skips_completed_attempts(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "bench.leaderboard.run._run_one", side_effect=AssertionError("should skip")
        ), patch("bench.leaderboard.run.current_tool_versions", return_value={}):
            out = Path(tmp) / "run"
            out.mkdir()
            (out / "attempts.jsonl").write_text(json.dumps(attempt_row()) + "\n", encoding="utf-8")

            result = run_experiment(
                self._plan(),
                model="fixture:reference",
                out=out,
                dry_run=False,
                confirm_spend=True,
                resume=True,
                force=False,
                max_generations=None,
                reps=1,
                temperature=0.2,
                top_p=1.0,
                max_tokens=4096,
                seed=None,
                if_retries=0,
                api_base=None,
                api_key_env="OPENAI_API_KEY",
                simulation_time_ms=None,
                allow_tool_version_mismatch=False,
                allow_unpublishable=False,
                cli_args={"resume": True},
            )

            self.assertEqual(result["attempts_written"], 0)
            self.assertEqual(result["attempts_skipped"], 1)

    def test_openai_raw_request_contains_messages_without_credentials(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [{"message": {"content": "void setup(){}\nvoid loop(){}\n"}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                    }
                ).encode("utf-8")

        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret"}, clear=False), patch(
            "urllib.request.urlopen", return_value=FakeResponse()
        ):
            response = generate_response(
                "openai:test-model",
                prompt="PROMPT",
                task=load_task("blink_led_1hz"),
                temperature=0.1,
            )

        request = response.raw["request"]
        self.assertEqual(request["body"]["messages"][1]["content"], "PROMPT")
        self.assertNotIn("Authorization", request["headers"])
        self.assertNotIn("secret", json.dumps(response.raw))


if __name__ == "__main__":
    unittest.main()


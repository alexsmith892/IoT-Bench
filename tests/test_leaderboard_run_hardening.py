import json
import tempfile
import unittest
import urllib.error
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
        "input_tokens": None,
        "base_input_tokens": None,
        "skill_input_tokens": None,
        "base_prompt_chars": 10,
        "skill_prompt_chars": 0,
        "output_tokens": None,
        "total_tokens": None,
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
        "extraction": {},
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
            self.assertEqual(experiment["status"], "complete")
            self.assertEqual(experiment["attempts_expected"], 1)
            self.assertEqual(experiment["attempts_missing"], 0)
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
            experiment = json.loads((out / "experiment.json").read_text(encoding="utf-8"))
            self.assertEqual(experiment["attempts_missing"], 0)

    def test_resume_requeues_inconclusive_if_attempts(self):
        # A prior run produced one BC (keep) and one IF (transient infra fail).
        # Resume must re-attempt only the IF row; the BC row stays untouched.
        plan = resolve_plan(
            "iot_skillsbench_v1",
            platform="arduino_mega",
            levels="1",
            skill_modes="none",
            task_ids="blink_led_1hz,blink_led_morse_code",
            reps=1,
        )
        bc_row = attempt_row("blink_led_1hz")
        if_row = attempt_row("blink_led_morse_code")
        if_row["result"] = "IF"
        if_row["classification"] = "SIM_INFRA_FAIL"
        rerun = attempt_row("blink_led_morse_code")  # now succeeds

        with tempfile.TemporaryDirectory() as tmp, patch(
            "bench.leaderboard.run._run_one", return_value=rerun
        ) as run_one, patch("bench.leaderboard.run.current_tool_versions", return_value={}):
            out = Path(tmp) / "run"
            out.mkdir()
            (out / "attempts.jsonl").write_text(
                json.dumps(bc_row) + "\n" + json.dumps(if_row) + "\n", encoding="utf-8"
            )

            result = run_experiment(
                plan,
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

            # Only the IF task was regenerated; the BC task was skipped.
            self.assertEqual(run_one.call_count, 1)
            self.assertEqual(result["attempts_written"], 1)
            self.assertEqual(result["attempts_skipped"], 1)
            self.assertEqual(result["attempts_missing"], 0)
            experiment = json.loads((out / "experiment.json").read_text(encoding="utf-8"))
            self.assertEqual(experiment["attempts_requeued_if"], 1)
            # The rewritten file must hold exactly one row per task, no IF, no dup keys.
            rows = [json.loads(line) for line in (out / "attempts.jsonl").read_text().splitlines() if line.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual({r["local_task_id"] for r in rows}, {"blink_led_1hz", "blink_led_morse_code"})
            self.assertNotIn("IF", {r["result"] for r in rows})

    def test_resume_partial_attempts_records_missing_count(self):
        plan = resolve_plan(
            "iot_skillsbench_v1",
            platform="arduino_mega",
            levels="1",
            skill_modes="none",
            task_ids="blink_led_1hz,blink_led_morse_code",
            reps=1,
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "bench.leaderboard.run._run_one", return_value=attempt_row("blink_led_morse_code")
        ), patch("bench.leaderboard.run.current_tool_versions", return_value={}):
            out = Path(tmp) / "run"
            out.mkdir()
            (out / "attempts.jsonl").write_text(json.dumps(attempt_row("blink_led_1hz")) + "\n", encoding="utf-8")

            result = run_experiment(
                plan,
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

            self.assertEqual(result["attempts_written"], 1)
            self.assertEqual(result["attempts_skipped"], 1)
            self.assertEqual(result["attempts_missing"], 0)

    def test_resume_corrupt_jsonl_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            out.mkdir()
            (out / "attempts.jsonl").write_text("{bad json\n", encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "malformed JSONL"):
                run_experiment(
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

    def test_resume_duplicate_jsonl_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            out.mkdir()
            row = json.dumps(attempt_row())
            (out / "attempts.jsonl").write_text(row + "\n" + row + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "duplicate attempt row"):
                run_experiment(
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

    def test_force_clears_owned_outputs_only(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "bench.leaderboard.run._run_one", return_value=attempt_row()
        ), patch("bench.leaderboard.run.current_tool_versions", return_value={}):
            out = Path(tmp) / "run"
            (out / "prompts").mkdir(parents=True)
            (out / "prompts" / "old.md").write_text("old", encoding="utf-8")
            (out / "reports").mkdir()
            (out / "reports" / "old.md").write_text("old", encoding="utf-8")
            (out / "notes.txt").write_text("keep", encoding="utf-8")

            run_experiment(
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
                cli_args={"force": True},
            )

            self.assertFalse((out / "prompts" / "old.md").exists())
            self.assertTrue((out / "notes.txt").exists())

    def test_interruption_records_status(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "bench.leaderboard.run._run_one", side_effect=KeyboardInterrupt
        ), patch("bench.leaderboard.run.current_tool_versions", return_value={}):
            out = Path(tmp) / "run"

            with self.assertRaises(KeyboardInterrupt):
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
                    cli_args={},
                )

            experiment = json.loads((out / "experiment.json").read_text(encoding="utf-8"))
            self.assertEqual(experiment["status"], "interrupted")

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
        self.assertEqual(response.usage["input_tokens"], 1)
        self.assertEqual(response.usage["output_tokens"], 2)

    def test_openai_retries_rate_limit(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "void setup(){}\nvoid loop(){}\n"}}]}).encode(
                    "utf-8"
                )

        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            429,
            "rate limited",
            {"Retry-After": "0"},
            None,
        )
        calls = [error, FakeResponse()]

        def fake_urlopen(*args, **kwargs):
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret"}, clear=False), patch(
            "urllib.request.urlopen", side_effect=fake_urlopen
        ), patch("time.sleep") as sleep:
            response = generate_response("openai:test-model", prompt="PROMPT", task=load_task("blink_led_1hz"))

        self.assertEqual(response.num_model_calls, 2)
        sleep.assert_called_once_with(0.0)

    def test_openai_missing_usage_keeps_usage_null(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "void setup(){}\nvoid loop(){}\n"}}]}).encode(
                    "utf-8"
                )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret"}, clear=False), patch(
            "urllib.request.urlopen", return_value=FakeResponse()
        ):
            response = generate_response("openai:test-model", prompt="PROMPT", task=load_task("blink_led_1hz"))

        self.assertIsNone(response.usage)

    def test_openai_auth_error_is_fatal_config(self):
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            401,
            "unauthorized",
            {},
            None,
        )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret"}, clear=False), patch(
            "urllib.request.urlopen", side_effect=error
        ), self.assertRaises(ConfigError):
            generate_response("openai:test-model", prompt="PROMPT", task=load_task("blink_led_1hz"))

    def test_provider_retry_exhaustion_becomes_if_attempt_row(self):
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            503,
            "unavailable",
            {"Retry-After": "0"},
            None,
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "secret", "IOTBENCH_PROVIDER_MAX_ATTEMPTS": "3"},
            clear=False,
        ), patch("urllib.request.urlopen", side_effect=error), patch("time.sleep"), patch(
            "bench.leaderboard.run.current_tool_versions", return_value={}
        ):
            out = Path(tmp) / "run"
            result = run_experiment(
                self._plan(),
                model="openai:test-model",
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
                api_base="https://example.test/v1",
                api_key_env="OPENAI_API_KEY",
                simulation_time_ms=None,
                allow_tool_version_mismatch=False,
                allow_unpublishable=False,
                cli_args={},
            )

            row = json.loads((out / "attempts.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(result["attempts_written"], 1)
            self.assertEqual(row["result"], "IF")
            self.assertEqual(row["failure_stage"], "generation")
            self.assertEqual(row["failure_source"], "harness")
            self.assertEqual(row["num_model_calls"], 3)

    def test_malformed_provider_response_becomes_if_attempt_row(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{not json"

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ", {"OPENAI_API_KEY": "secret"}, clear=False
        ), patch("urllib.request.urlopen", return_value=FakeResponse()), patch(
            "bench.leaderboard.run.current_tool_versions", return_value={}
        ):
            out = Path(tmp) / "run"
            run_experiment(
                self._plan(),
                model="openai:test-model",
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
                api_base="https://example.test/v1",
                api_key_env="OPENAI_API_KEY",
                simulation_time_ms=None,
                allow_tool_version_mismatch=False,
                allow_unpublishable=False,
                cli_args={},
            )

            row = json.loads((out / "attempts.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(row["result"], "IF")
            self.assertIn("malformed JSON", row["reason"])


if __name__ == "__main__":
    unittest.main()

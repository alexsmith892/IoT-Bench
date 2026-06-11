"""Offline checks for benchmark-operation commands and metadata."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench import cli
from bench.config import iter_platform_tasks, load_task
from bench.results import PASS, SIM_INFRA_FAIL, result_payload
from bench.runner import BuildSimulationError, generate_case


ROOT = Path(__file__).resolve().parents[1]


class PromptSidecarTests(unittest.TestCase):
    def test_all_supported_arduino_mega_tasks_have_frozen_prompts(self):
        tasks = list(iter_platform_tasks(platform="arduino_mega"))

        self.assertEqual(len(tasks), 41)
        for task in tasks:
            with self.subTest(task=task.task_id):
                self.assertTrue(task.prompt_path.exists())
                self.assertTrue(task.prompt_text.strip())
                self.assertTrue(task.prompt_text.endswith("\n"))

    def test_prompt_cli_prints_canonical_prompt_text(self):
        task = load_task("blink_led_1hz")

        with patch("builtins.print") as mocked_print:
            exit_code = cli.main(["prompt", "--task", "blink_led_1hz"])

        self.assertEqual(exit_code, 0)
        mocked_print.assert_called_once_with(task.prompt_text, end="")


class BatchEvaluateTests(unittest.TestCase):
    def test_evaluate_writes_jsonl_with_prompt_sketch_attempts_and_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sketch_dir = root / "submissions"
            sketch_dir.mkdir()
            (sketch_dir / "blink_led_1hz.ino").write_text("void setup(){}\nvoid loop(){}\n", encoding="utf-8")
            output = root / "results.jsonl"
            args = cli.parse_args([
                "evaluate",
                "--task",
                "blink_led_1hz",
                "--sketch-dir",
                str(sketch_dir),
                "--output",
                str(output),
            ])

            with patch("bench.cli.run_single_task", return_value=result_payload(PASS, "ok")):
                payload = cli.evaluate_submissions(args)

            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(payload["summary"], {"BC": 1})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["task_id"], "blink_led_1hz")
        self.assertEqual(row["final_result"]["result"], "BC")
        self.assertEqual(row["attempt_count"], 1)
        self.assertTrue(row["prompt_hash"])
        self.assertTrue(row["sketch_hash"])
        self.assertIn("tool_versions", row)

    def test_evaluate_retries_only_if_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sketch_dir = root / "submissions"
            sketch_dir.mkdir()
            (sketch_dir / "blink_led_1hz.ino").write_text("void setup(){}\nvoid loop(){}\n", encoding="utf-8")
            args = cli.parse_args([
                "evaluate",
                "--task",
                "blink_led_1hz",
                "--sketch-dir",
                str(sketch_dir),
                "--output",
                str(root / "results.jsonl"),
                "--if-retries",
                "1",
            ])

            with patch(
                "bench.cli.run_single_task",
                side_effect=[
                    result_payload(SIM_INFRA_FAIL, "transient"),
                    result_payload(PASS, "ok"),
                ],
            ):
                row = cli.evaluate_one_submission(load_task("blink_led_1hz"), args)

        self.assertEqual(row["attempt_count"], 2)
        self.assertEqual(row["attempts"][0]["result"]["result"], "IF")
        self.assertEqual(row["final_result"]["result"], "BC")

    def test_missing_batch_submission_is_cf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sketch_dir = root / "submissions"
            sketch_dir.mkdir()
            args = cli.parse_args([
                "evaluate",
                "--task",
                "blink_led_1hz",
                "--sketch-dir",
                str(sketch_dir),
                "--output",
                str(root / "results.jsonl"),
            ])

            row = cli.evaluate_one_submission(load_task("blink_led_1hz"), args)

        self.assertEqual(row["final_result"]["result"], "CF", row)
        self.assertEqual(row["attempt_count"], 1)


class RepeatabilityTests(unittest.TestCase):
    def test_repeatability_marks_non_bc_or_divergent_attempts_as_flaky(self):
        attempts = [
            {"attempt": 1, "result": result_payload(PASS, "ok")},
            {"attempt": 2, "result": result_payload(SIM_INFRA_FAIL, "transient")},
        ]
        args = cli.parse_args([
            "repeatability",
            "--task",
            "blink_led_1hz",
            "--runs",
            "2",
            "--output",
            "flakes.jsonl",
        ])

        row = cli.repeatability_row(load_task("blink_led_1hz"), attempts, args)

        self.assertTrue(row["flaky"])
        self.assertEqual(row["runs"], 2)


class ToolVersionTests(unittest.TestCase):
    def test_live_run_tool_version_mismatch_is_if(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task("blink_led_1hz")
            paths = generate_case(task, root=Path(tmp))
            mismatch = BuildSimulationError(
                "tool version mismatch",
                classification=SIM_INFRA_FAIL,
                failure_stage="simulate",
                failure_source="environment",
            )

            with patch("bench.cli.ensure_tool_versions_compatible", side_effect=mismatch):
                payload = cli.run_single_task(
                    task,
                    case_dir=paths.case_dir,
                    sketch_override=None,
                    use_existing_artifacts=False,
                    regenerate=False,
                    simulation_time_ms=None,
                    arduino_cli="arduino-cli",
                    wokwi_cli="wokwi-cli",
                    archived_vcd=None,
                )

        self.assertEqual(payload["result"], "IF", payload)
        self.assertEqual(payload["failure_source"], "environment", payload)


class CiWorkflowTests(unittest.TestCase):
    def test_github_actions_offline_ci_workflow_exists(self):
        workflow = ROOT / ".github" / "workflows" / "ci.yml"
        text = workflow.read_text(encoding="utf-8")

        self.assertIn("python -m unittest discover tests", text)


if __name__ == "__main__":
    unittest.main()

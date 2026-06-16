"""--use-existing-artifacts must refuse artifacts that don't match the manifest."""

from __future__ import annotations

import json
from subprocess import CompletedProcess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bench.cli import run_single_task
from bench import runner
from bench.config import TaskConfig, load_task
from bench.results import RESULT_BC, RESULT_IF, PASS, result_payload
from bench.runner import (
    BuildSimulationError,
    CasePaths,
    generate_case,
    validate_existing_artifact_manifest,
    write_verification,
)

from tests.validator_test_utils import blink_events, write_digital_vcd


def prepare_blink_case(root: Path):
    task = load_task("blink_led_1hz")
    paths = generate_case(task, root=root)
    assert paths.vcd is not None
    write_digital_vcd(paths.vcd, blink_events(0.5, cycles=6))
    paths.firmware_hex.parent.mkdir(parents=True, exist_ok=True)
    paths.firmware_hex.write_bytes(b"hex contents")
    paths.firmware_elf.write_bytes(b"elf contents")
    write_verification(task, paths, result_payload(PASS, "synthetic"), command="run")
    return task, paths


def validate_existing(task, paths, **kwargs):
    return run_single_task(
        task,
        case_dir=paths.case_dir,
        sketch_override=None,
        use_existing_artifacts=True,
        regenerate=False,
        simulation_time_ms=None,
        arduino_cli="arduino-cli",
        wokwi_cli="wokwi-cli",
        archived_vcd=None,
        **kwargs,
    )


class ArtifactProvenanceTests(unittest.TestCase):
    def test_matching_manifest_validates_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = prepare_blink_case(Path(tmp))
            payload = validate_existing(task, paths)
        self.assertEqual(payload["result"], RESULT_BC, payload)

    def test_sketch_changed_after_manifest_is_if(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = prepare_blink_case(Path(tmp))
            ino = next(paths.sketch.glob("*.ino"))
            ino.write_text(ino.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
            payload = validate_existing(task, paths)
        self.assertEqual(payload["result"], RESULT_IF, payload)
        self.assertEqual(payload["failure_source"], "artifact", payload)
        self.assertIn("sketch", payload["reason"], payload)

    def test_missing_manifest_is_if(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = prepare_blink_case(Path(tmp))
            (paths.case_dir / "artifacts" / "verification.json").unlink()
            payload = validate_existing(task, paths)
        self.assertEqual(payload["result"], RESULT_IF, payload)
        self.assertEqual(payload["failure_source"], "artifact", payload)

    def test_wrong_task_id_in_manifest_is_if(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = prepare_blink_case(Path(tmp))
            manifest_path = paths.case_dir / "artifacts" / "verification.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["task_id"] = "another_task"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            payload = validate_existing(task, paths)
        self.assertEqual(payload["result"], RESULT_IF, payload)

    def test_changed_vcd_after_manifest_is_if(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = prepare_blink_case(Path(tmp))
            assert paths.vcd is not None
            write_digital_vcd(paths.vcd, blink_events(0.3, cycles=6))
            payload = validate_existing(task, paths)
        self.assertEqual(payload["result"], RESULT_IF, payload)

    def test_allow_unverified_skips_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = prepare_blink_case(Path(tmp))
            (paths.case_dir / "artifacts" / "verification.json").unlink()
            payload = validate_existing(task, paths, require_provenance=False)
        self.assertEqual(payload["result"], RESULT_BC, payload)

    def test_idf_py_version_probe_ignores_wrapper_chatter(self):
        completed = CompletedProcess(
            args=["idf.py", "--version"],
            returncode=0,
            stdout=(
                "Done! You can now compile ESP-IDF projects.\n"
                "ESP-IDF v5.5.4\n"
            ),
            stderr="",
        )
        with mock.patch.object(runner.subprocess, "run", return_value=completed):
            self.assertEqual(runner.command_version("idf.py", "--version"), "ESP-IDF v5.5.4")


def variant_task(case_dir: Path) -> tuple[TaskConfig, CasePaths]:
    task = TaskConfig(
        path=case_dir / "task.yaml",
        data={
            "task_id": "bme280_read_i2c",
            "fixture": {"family": "composite", "components": []},
            "validator": {"family": "bme280_environment", "params": {}},
            "simulation_variants": [
                {"id": "scenario_a", "attrs": {}},
                {"id": "scenario_b", "attrs": {}},
            ],
            "case": {"id": case_dir.name, "sketch_name": "bme280_read_i2c"},
        },
    )
    paths = CasePaths(
        task_id="bme280_read_i2c",
        case_id=case_dir.name,
        case_dir=case_dir,
        sketch=case_dir / "sketch" / "bme280_read_i2c",
        diagram=case_dir / "diagram.json",
        wokwi_toml=case_dir / "wokwi.toml",
        build_dir=case_dir / "artifacts" / "build",
        fqbn="arduino:avr:mega",
        serial_log=case_dir / "artifacts" / "serial" / "serial.log",
    )
    return task, paths


def populate_variant_case(case_dir: Path) -> tuple[TaskConfig, CasePaths]:
    task, paths = variant_task(case_dir)
    task.path.write_text("task_id: bme280_read_i2c\n", encoding="utf-8")
    task.prompt_path.write_text("Read the BME280 over I2C.\n", encoding="utf-8")
    (case_dir / "case.yaml").write_text(
        "task_id: bme280_read_i2c\ncase_id: case\npaths:\n  sketch: sketch/bme280_read_i2c\n  diagram: diagram.json\n",
        encoding="utf-8",
    )
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "task": "bme280_read_i2c",
                "id": case_dir.name,
                "paths": {
                    "sketch": "sketch/bme280_read_i2c",
                    "diagram": "diagram.json",
                },
            }
        ),
        encoding="utf-8",
    )
    sketch_dir = paths.sketch
    sketch_dir.mkdir(parents=True)
    (sketch_dir / "bme280_read_i2c.ino").write_text("void setup(){}\nvoid loop(){}\n", encoding="utf-8")
    (case_dir / "diagram.json").write_text("{}", encoding="utf-8")
    paths.firmware_hex.parent.mkdir(parents=True, exist_ok=True)
    paths.firmware_hex.write_bytes(b"hex")
    paths.firmware_elf.write_bytes(b"elf")
    for sanitized in ("scenario_a", "scenario_b"):
        diagram = case_dir / "artifacts" / "variants" / sanitized / "diagram.json"
        diagram.parent.mkdir(parents=True, exist_ok=True)
        diagram.write_text("{}", encoding="utf-8")
        serial = case_dir / "artifacts" / "serial" / f"{sanitized}.serial.log"
        serial.parent.mkdir(parents=True, exist_ok=True)
        serial.write_text(f"output {sanitized}\n", encoding="utf-8")
    write_verification(task, paths, result_payload(PASS, "synthetic"), command="run")
    return task, paths


class VariantProvenanceTests(unittest.TestCase):
    def test_matching_variant_manifest_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = populate_variant_case(Path(tmp))
            validate_existing_artifact_manifest(task, paths)

    def test_variant_manifest_keeps_base_outputs_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, paths = populate_variant_case(Path(tmp))
            manifest = json.loads((paths.case_dir / "artifacts" / "verification.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["serial_log_path"])
        self.assertIsNone(manifest["serial_log_hash"])
        self.assertEqual(
            ["artifacts/serial/scenario_a.serial.log", "artifacts/serial/scenario_b.serial.log"],
            [entry["serial_log_path"] for entry in manifest["variants"]],
        )

    def test_changed_task_yaml_after_manifest_is_artifact_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = populate_variant_case(Path(tmp))
            task.path.write_text("task_id: bme280_read_i2c\n# changed\n", encoding="utf-8")
            with self.assertRaises(BuildSimulationError) as ctx:
                validate_existing_artifact_manifest(task, paths)
        self.assertEqual(ctx.exception.classification, "SIM_OUTPUT_FAIL")
        self.assertIn("task YAML", str(ctx.exception))

    def test_variant_missing_from_manifest_is_artifact_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = populate_variant_case(Path(tmp))
            manifest_path = paths.case_dir / "artifacts" / "verification.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["variants"] = manifest["variants"][:1]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(BuildSimulationError) as ctx:
                validate_existing_artifact_manifest(task, paths)
        self.assertEqual(ctx.exception.classification, "SIM_OUTPUT_FAIL")
        self.assertEqual(ctx.exception.failure_source, "artifact")

    def test_changed_variant_serial_log_is_artifact_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, paths = populate_variant_case(Path(tmp))
            serial = paths.case_dir / "artifacts" / "serial" / "scenario_b.serial.log"
            serial.write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(BuildSimulationError):
                validate_existing_artifact_manifest(task, paths)


if __name__ == "__main__":
    unittest.main()

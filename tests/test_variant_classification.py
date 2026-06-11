"""Variant validation must preserve inner classifications (IF stays IF, BF stays BF)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench.config import TaskConfig
from bench.results import RESULT_BC, RESULT_BF, RESULT_IF
from bench.runner import CasePaths, validate_case


def variant_task(case_dir: Path) -> tuple[TaskConfig, CasePaths]:
    task = TaskConfig(
        path=case_dir / "task.yaml",
        data={
            "task_id": "bme280_read_i2c",
            "fixture": {"family": "composite", "components": []},
            "validator": {
                "family": "bme280_environment",
                "params": {
                    "expected_temperature_c": 24.5,
                    "expected_humidity_rh": 55.0,
                },
            },
            "simulation_variants": [
                {
                    "id": "scenario_a",
                    "attrs": {"bme1": {"temperatureC": "24.5", "humidityRH": "55.0"}},
                    "validator": {"params": {"expected_temperature_c": 24.5, "expected_humidity_rh": 55.0}},
                },
                {
                    "id": "scenario_b",
                    "attrs": {"bme1": {"temperatureC": "31.0", "humidityRH": "42.0"}},
                    "validator": {"params": {"expected_temperature_c": 31.0, "expected_humidity_rh": 42.0}},
                },
            ],
            "simulation": {"require_distinct_variant_outputs": True},
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


def write_variant_serial(case_dir: Path, variant_id: str, text: str) -> None:
    serial_dir = case_dir / "artifacts" / "serial"
    serial_dir.mkdir(parents=True, exist_ok=True)
    (serial_dir / f"{variant_id}.serial.log").write_text(text, encoding="utf-8")


class VariantClassificationTests(unittest.TestCase):
    def test_all_variants_passing_is_bc(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = variant_task(case_dir)
            write_variant_serial(case_dir, "scenario_a", "Temperature: 24.5 C Humidity: 55.0 %\n")
            write_variant_serial(case_dir, "scenario_b", "Temperature: 31.0 C Humidity: 42.0 %\n")

            result = validate_case(task, paths)

        self.assertEqual(result["result"], RESULT_BC, result)
        self.assertEqual(len(result["metrics"]["variants"]), 2, result)

    def test_variant_behavior_failure_stays_bf(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = variant_task(case_dir)
            write_variant_serial(case_dir, "scenario_a", "Temperature: 24.5 C Humidity: 55.0 %\n")
            write_variant_serial(case_dir, "scenario_b", "Temperature: 99.0 C Humidity: 1.0 %\n")

            result = validate_case(task, paths)

        self.assertEqual(result["result"], RESULT_BF, result)
        self.assertEqual(result["classification"], "FAIL", result)
        self.assertIn("variant scenario_b failed:", result["reason"], result)

    def test_missing_variant_serial_log_is_if_not_bf(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = variant_task(case_dir)
            write_variant_serial(case_dir, "scenario_a", "Temperature: 24.5 C Humidity: 55.0 %\n")
            # scenario_b serial log intentionally absent.

            result = validate_case(task, paths)

        self.assertEqual(result["result"], RESULT_IF, result)
        self.assertEqual(result["classification"], "SIM_OUTPUT_FAIL", result)
        self.assertEqual(result["failure_source"], "artifact", result)
        self.assertIn("scenario_b", result["reason"], result)
        # Per-variant metrics gathered before the failure are preserved.
        self.assertIn("variants", result["metrics"], result)

    def test_all_variant_serial_logs_missing_is_if(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = variant_task(case_dir)

            result = validate_case(task, paths)

        self.assertEqual(result["result"], RESULT_IF, result)
        self.assertEqual(result["classification"], "SIM_OUTPUT_FAIL", result)


if __name__ == "__main__":
    unittest.main()

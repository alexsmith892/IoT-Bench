"""Per-variant scenario overrides: paths, proxy tasks, and scenario generation."""

from __future__ import annotations

import unittest
from pathlib import Path

from bench.config import TaskConfig
from bench.runner import (
    CasePaths,
    paths_for_variant,
    task_for_variant,
    variant_scenario_override,
)
from bench.scenarios import generate_scenario


BASE_SCENARIO = {
    "family": "control_sequence",
    "initial_delay_ms": 200,
    "controls": [{"part_id": "imu1", "control": "accelX", "value": 0.5, "duration_ms": 400}],
}
OVERRIDE_SCENARIO = {
    "family": "control_sequence",
    "initial_delay_ms": 200,
    "controls": [{"part_id": "imu1", "control": "accelX", "value": 1.5, "duration_ms": 400}],
}


def stub_task(scenario: dict | None) -> TaskConfig:
    data = {
        "task_id": "stub",
        "fixture": {"family": "composite", "components": []},
        "validator": {"family": "serial_regex_sequence", "params": {"patterns": ["x"]}},
        "simulation": {"timeout_ms": 1200},
        "case": {"id": "stub-case", "sketch_name": "stub"},
    }
    if scenario is not None:
        data["scenario"] = scenario
    return TaskConfig(path=Path("task.yaml"), data=data)


def stub_paths(case_dir: Path, *, scenario: bool) -> CasePaths:
    return CasePaths(
        task_id="stub",
        case_id="stub-case",
        case_dir=case_dir,
        sketch=case_dir / "sketch" / "stub",
        diagram=case_dir / "diagram.json",
        wokwi_toml=case_dir / "wokwi.toml",
        build_dir=case_dir / "artifacts" / "build",
        fqbn="arduino:avr:mega",
        scenario=(case_dir / "scenario.yaml" if scenario else None),
        serial_log=case_dir / "artifacts" / "serial" / "serial.log",
    )


class VariantScenarioOverrideTests(unittest.TestCase):
    def test_override_detection(self):
        self.assertIsNone(variant_scenario_override({"id": "a"}))
        self.assertIsNone(variant_scenario_override(None))
        self.assertEqual(
            variant_scenario_override({"id": "a", "scenario": OVERRIDE_SCENARIO}),
            OVERRIDE_SCENARIO,
        )

    def test_paths_use_per_variant_scenario_only_when_overridden(self):
        case_dir = Path("case")
        paths = stub_paths(case_dir, scenario=True)
        plain = paths_for_variant(paths, "a", {"id": "a"})
        self.assertEqual(plain.scenario, case_dir / "scenario.yaml")
        overridden = paths_for_variant(paths, "b", {"id": "b", "scenario": OVERRIDE_SCENARIO})
        self.assertEqual(
            overridden.scenario, case_dir / "artifacts" / "variants" / "b" / "scenario.yaml"
        )

    def test_variant_scenario_works_without_base_scenario(self):
        # A task whose stimulus exists only in variants still gets a scenario path.
        case_dir = Path("case")
        paths = stub_paths(case_dir, scenario=False)
        overridden = paths_for_variant(paths, "a", {"id": "a", "scenario": OVERRIDE_SCENARIO})
        self.assertEqual(
            overridden.scenario, case_dir / "artifacts" / "variants" / "a" / "scenario.yaml"
        )

    def test_task_for_variant_replaces_scenario_wholesale(self):
        task = stub_task(BASE_SCENARIO)
        proxy = task_for_variant(task, {"id": "a", "scenario": OVERRIDE_SCENARIO})
        self.assertEqual(proxy.scenario, OVERRIDE_SCENARIO)
        # The base task data must remain untouched.
        self.assertEqual(task.scenario, BASE_SCENARIO)
        # Without an override the base scenario is kept.
        plain = task_for_variant(task, {"id": "b"})
        self.assertEqual(plain.scenario, BASE_SCENARIO)

    def test_generate_scenario_uses_variant_override(self):
        task = stub_task(BASE_SCENARIO)
        proxy = task_for_variant(task, {"id": "a", "scenario": OVERRIDE_SCENARIO})
        generated = generate_scenario(proxy)
        values = [
            step["set-control"]["value"]
            for step in generated["steps"]
            if "set-control" in step
        ]
        self.assertEqual(values, [1.5])


if __name__ == "__main__":
    unittest.main()

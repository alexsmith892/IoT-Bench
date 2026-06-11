"""Scenario set-control targets must match real diagram parts and known controls."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from bench.config import TaskConfig, iter_tasks, load_task
from bench.diagrams import (
    DiagramError,
    PART_TYPE_CONTROLS,
    generate_diagram,
    validate_scenario_controls,
)
from bench.runner import generate_case


def dht_task(scenario_controls: list[dict]) -> TaskConfig:
    base = load_task("dht11_read", level="level2")
    data = copy.deepcopy(base.data)
    data["scenario"]["controls"] = scenario_controls
    return TaskConfig(path=base.path, data=data)


class ScenarioControlLintTests(unittest.TestCase):
    def test_known_controls_pass(self):
        task = load_task("dht11_read", level="level2")
        validate_scenario_controls(generate_diagram(task), task)

    def test_unknown_part_id_fails(self):
        task = dht_task([{"part_id": "dht999", "control": "temperature", "value": 20, "duration_ms": 250}])
        with self.assertRaises(DiagramError) as ctx:
            validate_scenario_controls(generate_diagram(task), task)
        self.assertIn("unknown part id", str(ctx.exception))

    def test_unknown_control_name_fails(self):
        task = dht_task([{"part_id": "dht1", "control": "temperatre", "value": 20, "duration_ms": 250}])
        with self.assertRaises(DiagramError) as ctx:
            validate_scenario_controls(generate_diagram(task), task)
        self.assertIn("temperatre", str(ctx.exception))

    def test_unknown_variant_attr_on_custom_chip_fails(self):
        base = load_task("bme280_read_i2c", level="level2")
        data = copy.deepcopy(base.data)
        data["simulation_variants"][0]["attrs"]["bme1"] = {"temperatureX": "1"}
        task = TaskConfig(path=base.path, data=data)
        with self.assertRaises(DiagramError) as ctx:
            validate_scenario_controls(generate_diagram(task), task)
        self.assertIn("temperatureX", str(ctx.exception))

    def test_variant_attr_on_unknown_part_fails(self):
        base = load_task("bme280_read_i2c", level="level2")
        data = copy.deepcopy(base.data)
        data["simulation_variants"][0]["attrs"] = {"nope1": {"temperatureC": "1"}}
        task = TaskConfig(path=base.path, data=data)
        with self.assertRaises(DiagramError):
            validate_scenario_controls(generate_diagram(task), task)

    def test_every_supported_task_passes_the_control_lint(self):
        # Backstop: an allowlist omission must fail here, not during a live run.
        with tempfile.TemporaryDirectory() as tmp:
            for level in ("level1", "level2", "level3"):
                for task in iter_tasks(level=level):
                    if not task.is_supported:
                        continue
                    with self.subTest(task=task.task_id):
                        generate_case(task, root=Path(tmp))  # calls validate_diagram_file

    def test_allowlist_controls_are_nonempty(self):
        for part_type, controls in PART_TYPE_CONTROLS.items():
            self.assertTrue(controls, part_type)


if __name__ == "__main__":
    unittest.main()

"""Renode-tree lint: mirrors tests/test_scenario_control_lint.py for Wokwi.

Scenario set-control targets must resolve to parts the Renode fixture
declares, controls must be in RENODE_PERIPHERAL_CONTROLS, variant scenario
overrides get the same lint, and per-variant attrs (unsupported by this
backend) must fail at lint time rather than during a live run.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from bench.config import TaskConfig, iter_platform_tasks
from bench.renode import (
    RENODE_PERIPHERAL_CONTROLS,
    RenodeConfigError,
    validate_variant_scenarios,
)
from bench.runner import generate_case

PLATFORM = "zephyr_nano33ble"


def platform_tasks() -> list[TaskConfig]:
    return list(iter_platform_tasks(platform=PLATFORM, levels=["level1"]))


class RenodeScenarioLintTests(unittest.TestCase):
    def test_every_supported_task_generates_and_lints(self) -> None:
        # Backstop, same as the Wokwi control lint: an allowlist omission or
        # unsupported fixture must fail here, not during a live run.
        tasks = platform_tasks()
        self.assertTrue(tasks, f"no tasks found for {PLATFORM}")
        with tempfile.TemporaryDirectory() as tmp:
            for task in tasks:
                if not task.is_supported:
                    continue
                with self.subTest(task=task.task_id):
                    generate_case(task, root=Path(tmp))

    def test_variant_attrs_rejected(self) -> None:
        base = platform_tasks()[0]
        data = copy.deepcopy(base.data)
        data["simulation_variants"] = [{"id": "a", "attrs": {"btn1": {"bounce": "false"}}}]
        task = TaskConfig(path=base.path, data=data)
        with self.assertRaises(RenodeConfigError) as ctx:
            validate_variant_scenarios(task)
        self.assertIn("attrs", str(ctx.exception))

    def test_variant_scenario_with_unknown_part_rejected(self) -> None:
        base = platform_tasks()[0]
        data = copy.deepcopy(base.data)
        data["simulation_variants"] = [
            {
                "id": "a",
                "scenario": {
                    "family": "button_press_sequence",
                    "part_id": "ghost1",
                    "presses": [{"duration_ms": 100, "after_ms": 100}],
                },
            }
        ]
        task = TaskConfig(path=base.path, data=data)
        with self.assertRaises(RenodeConfigError) as ctx:
            validate_variant_scenarios(task)
        self.assertIn("ghost1", str(ctx.exception))

    def test_allowlist_controls_are_nonempty(self) -> None:
        for part_type, controls in RENODE_PERIPHERAL_CONTROLS.items():
            self.assertTrue(controls, part_type)


if __name__ == "__main__":
    unittest.main()

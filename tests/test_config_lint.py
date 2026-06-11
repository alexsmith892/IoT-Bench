"""Config-time lint checks: variant id uniqueness and simulation budget guards."""

from __future__ import annotations

import unittest
from pathlib import Path

from bench.config import (
    ConfigError,
    TaskConfig,
    iter_tasks,
    sanitize_variant_id,
    scenario_end_ms,
    validate_simulation_budget,
    validate_simulation_variants,
)


def stub_task() -> TaskConfig:
    return TaskConfig(path=Path("task.yaml"), data={"task_id": "stub"})


class VariantIdLintTests(unittest.TestCase):
    def test_distinct_variant_ids_pass(self):
        validate_simulation_variants(
            stub_task(),
            [{"id": "scenario_a"}, {"id": "scenario_b"}],
        )

    def test_colliding_sanitized_ids_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_simulation_variants(
                stub_task(),
                [{"id": "a:b"}, {"id": "a b"}],
            )
        self.assertIn("collide", str(ctx.exception))

    def test_exact_duplicate_ids_rejected(self):
        with self.assertRaises(ConfigError):
            validate_simulation_variants(
                stub_task(),
                [{"id": "scenario_a"}, {"id": "scenario_a"}],
            )

    def test_id_sanitizing_to_empty_rejected(self):
        with self.assertRaises(ConfigError):
            validate_simulation_variants(stub_task(), [{"id": "::"}])

    def test_sanitize_variant_id_behavior(self):
        self.assertEqual(sanitize_variant_id("scenario_a"), "scenario_a")
        self.assertEqual(sanitize_variant_id("a:b"), "a-b")
        self.assertEqual(sanitize_variant_id("a b"), "a-b")
        self.assertEqual(sanitize_variant_id("::"), "")


def variant_scenario_task(timeout_ms: float) -> TaskConfig:
    return TaskConfig(
        path=Path("task.yaml"),
        data={"task_id": "stub", "simulation": {"timeout_ms": timeout_ms}},
    )


class VariantScenarioLintTests(unittest.TestCase):
    SCENARIO = {
        "family": "control_sequence",
        "initial_delay_ms": 200,
        "controls": [{"part_id": "imu1", "control": "accelX", "value": 0.5, "duration_ms": 600}],
    }

    def test_valid_variant_scenario_passes(self):
        validate_simulation_variants(
            variant_scenario_task(1200),
            [{"id": "a", "scenario": self.SCENARIO}, {"id": "b"}],
        )

    def test_variant_scenario_must_be_mapping(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_simulation_variants(
                variant_scenario_task(1200), [{"id": "a", "scenario": ["x"]}]
            )
        self.assertIn("must be a mapping", str(ctx.exception))

    def test_variant_scenario_unknown_family_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_simulation_variants(
                variant_scenario_task(1200), [{"id": "a", "scenario": {"family": "nope"}}]
            )
        self.assertIn("unknown scenario family", str(ctx.exception))

    def test_variant_scenario_structure_validated(self):
        broken = {"family": "control_sequence", "controls": [{"part_id": "p", "value": 1, "duration_ms": 100}]}
        with self.assertRaises(ConfigError):
            validate_simulation_variants(variant_scenario_task(1200), [{"id": "a", "scenario": broken}])

    def test_variant_scenario_budget_enforced_per_variant(self):
        # The variant timeline (800 ms) exceeds the simulation timeout (700 ms).
        with self.assertRaises(ConfigError):
            validate_simulation_variants(
                variant_scenario_task(700), [{"id": "a", "scenario": self.SCENARIO}]
            )


def budget_task(scenario: dict, timeout_ms: float) -> TaskConfig:
    return TaskConfig(
        path=Path("task.yaml"),
        data={
            "task_id": "stub",
            "scenario": scenario,
            "simulation": {"timeout_ms": timeout_ms},
        },
    )


class SimulationBudgetTests(unittest.TestCase):
    CONTROL_SCENARIO = {
        "family": "control_sequence",
        "initial_delay_ms": 200,
        "controls": [
            {"part_id": "p", "control": "c", "value": 1, "duration_ms": 500},
            {"part_id": "p", "control": "c", "value": 0, "duration_ms": 800},
        ],
    }

    def test_scenario_end_ms_per_family(self):
        self.assertEqual(scenario_end_ms(self.CONTROL_SCENARIO), 1500.0)
        self.assertEqual(
            scenario_end_ms(
                {
                    "family": "button_press_sequence",
                    "initial_delay_ms": 100,
                    "presses": [{"duration_ms": 150, "after_ms": 250}],
                }
            ),
            500.0,
        )
        self.assertEqual(
            scenario_end_ms(
                {
                    "family": "timeline",
                    "steps": [{"delay_ms": 300}, {"set_control": {}}, {"delay_ms": 700}],
                }
            ),
            1000.0,
        )

    def test_timeout_not_exceeding_scenario_end_is_rejected(self):
        with self.assertRaises(ConfigError):
            validate_simulation_budget(budget_task(self.CONTROL_SCENARIO, 1500))
        with self.assertRaises(ConfigError):
            validate_simulation_budget(budget_task(self.CONTROL_SCENARIO, 1000))

    def test_timeout_above_scenario_end_passes(self):
        validate_simulation_budget(budget_task(self.CONTROL_SCENARIO, 1800))

    def test_all_real_tasks_satisfy_the_budget_lint(self):
        for level in ("level1", "level2", "level3"):
            for task in iter_tasks(level=level):
                with self.subTest(task=task.task_id):
                    validate_simulation_budget(task)


if __name__ == "__main__":
    unittest.main()

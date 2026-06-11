"""Adversarial stub corpus: hardcoded cheats must keep failing their oracles.

Each stub under tests/adversarial/<task_id>/ is a known cheat for that task.
Stubs marked static_fail=True must be rejected offline by the task's static
checks. Stubs marked static_fail=False intentionally satisfy the static gate
(decoy calls) and are rejected at runtime by variant oracles instead - that
rejection is verified by live swap runs (see the oracle-hardening notes), and
this test pins the static-gate expectation either way so a change in behavior
is a conscious decision.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from bench.config import TaskConfig, load_task, repo_root
from bench.static import StaticCheckError, validate_static_checks

# (task_id, level, stub filename, expected to fail the static gate)
STUBS = [
    ("ds1307_rtc", "level2", "stub_hardcoded.ino", True),
    ("ds1307_rtc", "level2", "stub_i2c_decoy.ino", False),
    ("mpu6050_read_i2c", "level2", "stub_hardcoded.ino", True),
    ("mpu6050_read_i2c", "level2", "stub_i2c_decoy.ino", False),
    ("hcsr04_find_distance", "level2", "stub_pulse_decoy.ino", False),
    ("dht11_read_button_display", "level3", "stub_hardcoded.ino", False),
    ("tmp36_read_button_display", "level3", "stub_hardcoded.ino", False),
    ("tmp36_read_periodic_display", "level3", "stub_hardcoded.ino", False),
    ("mpu6050_read_button_display", "level3", "stub_hardcoded.ino", False),
    ("mpu6050_read_periodic_display", "level3", "stub_hardcoded.ino", False),
    ("reaction_timer_display", "level3", "stub_hardcoded.ino", False),
    ("safebox_display", "level3", "stub_hardcoded.ino", False),
    ("sensor_pir_human_motion", "level1", "stub_hardcoded.ino", False),
    ("button_press_debounce", "level1", "stub_hardcoded.ino", False),
]


def static_params(task: TaskConfig) -> dict:
    if task.validator_family == "static_checks":
        return task.validator_params()
    if task.validator_family == "composite":
        for check in task.validator.get("checks", []):
            if check.get("family") == "static_checks":
                return check.get("params") or {}
    return {}


class AdversarialStaticTests(unittest.TestCase):
    def test_corpus_files_exist(self):
        for task_id, _level, stub, _expect_fail in STUBS:
            path = repo_root() / "tests" / "adversarial" / task_id / stub
            self.assertTrue(path.exists(), path)

    def test_static_gate_expectations(self):
        for task_id, level, stub, expect_fail in STUBS:
            with self.subTest(task=task_id, stub=stub):
                task = load_task(task_id, level=level)
                params = static_params(task)
                self.assertTrue(params, f"{task_id} has no static checks to pin")
                path = repo_root() / "tests" / "adversarial" / task_id / stub
                if expect_fail:
                    with self.assertRaises(StaticCheckError):
                        validate_static_checks(path, params)
                else:
                    # Passing the static gate is intentional for decoy stubs;
                    # their rejection is the runtime variant oracle's job.
                    validate_static_checks(path, params)

    def test_hardened_tasks_demand_runtime_distinguishers(self):
        # Every task in the corpus must have either simulation variants or a
        # scenario-correlated oracle; a single fixed expectation is hardcodable.
        for task_id, level, _stub, _expect_fail in STUBS:
            with self.subTest(task=task_id):
                task = load_task(task_id, level=level)
                self.assertTrue(
                    task.simulation_variants or task.scenario,
                    f"{task_id} has neither variants nor a stimulus scenario",
                )


if __name__ == "__main__":
    unittest.main()

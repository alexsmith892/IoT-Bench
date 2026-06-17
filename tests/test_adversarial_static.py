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

import json
import re
import unittest
from pathlib import Path

from bench.config import TaskConfig, load_task, repo_root
from bench.static import StaticCheckError, validate_static_checks

ZEPHYR_PLATFORM = "zephyr_nano33ble"
ZEPHYR_ORACLE_INVENTORY = repo_root() / "docs" / "zephyr-oracle-inventory.md"
UPSTREAM_ZEPHYR_FIXTURE = repo_root() / "tests" / "fixtures" / "upstream_zephyr_tasks.json"

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


# Zephyr (zephyr_nano33ble) corpus: same contract, C sources instead of .ino.
# (task_id, level, stub filename, expected to fail the static gate)
ZEPHYR_STUBS = [
    ("blink_led_no_delay", "level1", "stub_zephyr_delay_loop.c", True),
    ("button_status_count", "level1", "stub_zephyr_print_only.c", True),
    ("button_status_count", "level1", "stub_zephyr_decoy_fixed_count.c", False),
    ("button_press_debounce", "level1", "stub_zephyr_print_only.c", True),
    ("button_press_debounce", "level1", "stub_zephyr_decoy_two_triggers.c", False),
    ("sensor_pir_human_motion", "level1", "stub_zephyr_print_only.c", True),
    ("sensor_pir_human_motion", "level1", "stub_zephyr_decoy_hardcoded.c", False),
    ("ds1307_rtc", "level2", "stub_zephyr_print_only.c", True),
    ("ds1307_rtc", "level2", "stub_zephyr_decoy_hardcoded.c", False),
    ("lsm9ds1_read_i2c", "level2", "stub_zephyr_print_only.c", True),
    ("lsm9ds1_read_i2c", "level2", "stub_zephyr_decoy_hardcoded.c", False),
    ("bme280_read_i2c", "level2", "stub_zephyr_print_only.c", True),
    ("bme280_read_i2c", "level2", "stub_zephyr_decoy_hardcoded.c", False),
    ("bme280_read_spi", "level2", "stub_zephyr_print_only.c", True),
    ("bme280_read_spi", "level2", "stub_zephyr_i2c_decoy.c", True),
    ("tmp36_read", "level1", "stub_zephyr_print_only.c", True),
    ("tmp36_read", "level1", "stub_zephyr_decoy_hardcoded.c", False),
    ("mpu6050_read_i2c", "level2", "stub_zephyr_print_only.c", True),
    ("mpu6050_read_i2c", "level2", "stub_zephyr_decoy_hardcoded.c", False),
    ("rotary_encoder", "level2", "stub_zephyr_print_only.c", True),
    ("rotary_encoder", "level2", "stub_zephyr_decoy_hardcoded.c", False),
    ("16key_keypad", "level2", "stub_zephyr_print_only.c", True),
    ("16key_keypad", "level2", "stub_zephyr_decoy_hardcoded.c", False),
    ("photoresistor_nightlight", "level2", "stub_zephyr_schedule_replay.c", True),
    ("photoresistor_nightlight", "level2", "stub_zephyr_decoy_schedule.c", False),
    ("safebox", "level3", "stub_zephyr_timer_unlock.c", True),
    ("safebox", "level3", "stub_zephyr_decoy_timer_unlock.c", False),
    ("step_counter_print", "level3", "stub_zephyr_print_only.c", True),
    ("step_counter_print", "level3", "stub_zephyr_decoy_hardcoded.c", False),
    ("hcsr04_find_distance", "level2", "stub_zephyr_print_only.c", True),
    ("hcsr04_find_distance", "level2", "stub_zephyr_decoy_hardcoded.c", False),
    ("parking_sensor", "level2", "stub_zephyr_fixed_buzzer.c", False),
    ("reverse_parking_sensor", "level2", "stub_zephyr_fixed_buzzer.c", False),
    ("mpu6050_read_periodic_display", "level3", "stub_zephyr_hardcoded_lcd.c", False),
    ("joystick_buzzer_pitch", "level3", "stub_zephyr_fixed_pitch.c", False),
]

# Runtime-only Zephyr tasks that deliberately have no static gate. These stubs
# are active compile-shaped submissions and are rejected by live waveform/LCD
# oracles, not by validate_static_checks().
ZEPHYR_RUNTIME_ONLY_STUBS = [
    ("blink_led_1hz", "level1", "stub_zephyr_wrong_frequency.c"),
    ("blink_led_morse_code", "level1", "stub_zephyr_wrong_morse.c"),
    ("breathing_led", "level1", "stub_zephyr_flat_pwm.c"),
    ("lcd1602_display_hello_world", "level2", "stub_zephyr_wrong_text.c"),
]


def canonical_zephyr_levels() -> dict[str, str]:
    data = json.loads(UPSTREAM_ZEPHYR_FIXTURE.read_text(encoding="utf-8"))
    levels: dict[str, str] = {}
    for level in ("level1", "level2", "level3"):
        task_ids = data[level]
        for task_id in task_ids:
            levels[task_id] = level
    return levels


def inventory_rows(section: str) -> list[tuple[str, str, str]]:
    text = ZEPHYR_ORACLE_INVENTORY.read_text(encoding="utf-8")
    rows: list[tuple[str, str, str]] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line.strip() == f"## {section}"
            continue
        if not in_section or not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            raise AssertionError(f"malformed inventory row: {line}")
        task_match = re.fullmatch(r"`([^`]+)`", cells[0])
        if not task_match:
            raise AssertionError(f"inventory task cell must be backtick quoted: {line}")
        rows.append((task_match.group(1), cells[1], cells[2]))
    return rows


def zephyr_static_params(task: TaskConfig) -> dict:
    params = static_params(task)
    if params:
        return params
    return task.static_checks


class ZephyrAdversarialStaticTests(unittest.TestCase):
    def test_corpus_files_exist(self):
        for task_id, _level, stub, _expect_fail in ZEPHYR_STUBS:
            path = repo_root() / "tests" / "adversarial" / task_id / stub
            self.assertTrue(path.exists(), path)
        for task_id, _level, stub in ZEPHYR_RUNTIME_ONLY_STUBS:
            path = repo_root() / "tests" / "adversarial" / task_id / stub
            self.assertTrue(path.exists(), path)

    def test_static_gate_expectations(self):
        for task_id, level, stub, expect_fail in ZEPHYR_STUBS:
            with self.subTest(task=task_id, stub=stub):
                task = load_task(task_id, platform="zephyr_nano33ble", level=level)
                params = zephyr_static_params(task)
                self.assertTrue(params, f"{task_id} has no static checks to pin")
                path = repo_root() / "tests" / "adversarial" / task_id / stub
                if expect_fail:
                    with self.assertRaises(StaticCheckError):
                        validate_static_checks(path, params, build_kind="zephyr")
                else:
                    # Decoys intentionally pass the static gate; their runtime
                    # rejection is pinned by live swap runs (variant oracles).
                    validate_static_checks(path, params, build_kind="zephyr")

    def test_hardened_tasks_demand_runtime_distinguishers(self):
        # Waveform-judged tasks (requires_vcd) are inherently not hardcodable
        # through serial output; everything else needs variants or a stimulus.
        for task_id, level, _stub, _expect_fail in ZEPHYR_STUBS:
            with self.subTest(task=task_id):
                task = load_task(task_id, platform="zephyr_nano33ble", level=level)
                self.assertTrue(
                    task.simulation_variants or task.scenario or task.requires_vcd,
                    f"{task_id} has neither variants, a stimulus scenario, nor a waveform oracle",
                )

    def test_runtime_only_stubs_have_runtime_oracles(self):
        for task_id, level, _stub in ZEPHYR_RUNTIME_ONLY_STUBS:
            with self.subTest(task=task_id):
                task = load_task(task_id, platform=ZEPHYR_PLATFORM, level=level)
                self.assertFalse(
                    zephyr_static_params(task),
                    f"{task_id} unexpectedly has static checks; move it to ZEPHYR_STUBS",
                )
                self.assertTrue(
                    task.requires_vcd,
                    f"{task_id} runtime-only adversarial stub needs a waveform/LCD oracle",
                )

    def test_oracle_inventory_covers_exact_canonical_zephyr_set(self):
        canonical = canonical_zephyr_levels()
        rows = inventory_rows("Canonical Tasks")
        task_ids = [task_id for task_id, _level, _defense in rows]

        self.assertEqual(42, len(rows))
        self.assertEqual(len(task_ids), len(set(task_ids)), "duplicate canonical inventory row")
        self.assertEqual(set(canonical), set(task_ids))
        for task_id, level, _defense in rows:
            self.assertEqual(canonical[task_id], level, task_id)

    def test_oracle_inventory_lists_addition_separately(self):
        canonical_ids = set(canonical_zephyr_levels())
        additions = inventory_rows("Non-Canonical Addition")
        self.assertEqual(
            [("lsm9ds1_read_i2c", "level2")],
            [(task_id, level) for task_id, level, _defense in additions],
        )
        self.assertFalse(canonical_ids & {task_id for task_id, _level, _defense in additions})

    def test_oracle_inventory_names_concrete_defenses(self):
        text = ZEPHYR_ORACLE_INVENTORY.read_text(encoding="utf-8")
        self.assertNotRegex(text.lower(), r"\b(todo|unknown)\b")

        defense_tokens = (
            "Behavior-distinct variants",
            "`window_ratios`",
            "`frequency_windows`",
            "`stimulus_to_output`",
            "`serial_contains_on_stimulus`",
            "`serial_count_sequence`",
            "`serial_observation_sequence`",
            "`debounce_serial`",
            "`bme280_environment`",
            "`bus_activity`",
            "fixed-by-spec",
        )
        for section in ("Canonical Tasks", "Non-Canonical Addition"):
            for task_id, _level, defense in inventory_rows(section):
                with self.subTest(task=task_id):
                    self.assertTrue(
                        any(token in defense for token in defense_tokens),
                        f"{task_id}: inventory defense is not concrete: {defense}",
                    )


ESPIDF_STUBS = [
    ("dht11_read", "level2", "stub_espidf_hardcoded.c", False),
    ("ds1307_rtc", "level2", "stub_espidf_hardcoded.c", False),
    ("ds18b20_heat_alarm", "level2", "stub_espidf_wrong_pin_hardcoded.c", False),
    ("hcsr04_find_distance", "level2", "stub_espidf_hardcoded_distance.c", True),
    ("parking_sensor", "level2", "stub_espidf_fixed_buzzer.c", False),
    ("reverse_parking_sensor", "level2", "stub_espidf_fixed_buzzer.c", False),
    ("rotary_encoder", "level2", "stub_espidf_hardcoded_sequence.c", False),
    ("clap_switch", "level2", "stub_espidf_fixed_toggle.c", False),
    ("photoresistor_nightlight", "level2", "stub_espidf_fixed_light.c", False),
    ("dht11_read_button_display", "level3", "stub_espidf_hardcoded.c", False),
    ("lcd1602_auto_brightness_control", "level3", "stub_espidf_fixed_pwm.c", False),
    ("tmp36_read_button_display", "level3", "stub_espidf_hardcoded_lcd.c", True),
    ("tmp36_read_periodic_display", "level3", "stub_espidf_hardcoded_lcd.c", True),
    ("mpu6050_read_button_display", "level3", "stub_espidf_hardcoded.c", False),
    ("mpu6050_read_periodic_display", "level3", "stub_espidf_hardcoded.c", False),
    ("buzzer_toggle_led_freq", "level3", "stub_espidf_fixed_frequency.c", False),
    ("reaction_timer_display", "level3", "stub_espidf_fixed_elapsed.c", False),
    ("buzzer_laser_tripwire", "level3", "stub_espidf_fixed_alarm.c", False),
    ("joystick_buzzer_pitch", "level3", "stub_espidf_fixed_pitch.c", False),
    ("safebox", "level3", "stub_espidf_timer_unlock.c", False),
    ("safebox_display", "level3", "stub_espidf_hardcoded.c", False),
    ("step_counter_print", "level3", "stub_espidf_hardcoded_steps.c", False),
    # Print-only static-reject stubs for tasks that previously had no ESP-IDF
    # adversarial coverage (their required real-I/O patterns are absent).
    ("hcsr501_motion_alarm", "level2", "stub_espidf_print_only.c", True),
    ("tilt_detection_alarm", "level2", "stub_espidf_print_only.c", True),
    ("mpu6050_read_spi", "level2", "stub_espidf_print_only.c", True),
    ("sensor_water_level_display", "level3", "stub_espidf_print_only.c", True),
]


class EspIdfAdversarialStaticTests(unittest.TestCase):
    def test_corpus_files_exist(self):
        for task_id, _level, stub, _expect_fail in ESPIDF_STUBS:
            path = repo_root() / "tests" / "adversarial" / task_id / stub
            self.assertTrue(path.exists(), path)

    def test_static_gate_expectations(self):
        for task_id, level, stub, expect_fail in ESPIDF_STUBS:
            with self.subTest(task=task_id, stub=stub):
                task = load_task(task_id, platform="esp32s3_espidf", level=level)
                params = static_params(task)
                self.assertTrue(params, f"{task_id} has no static checks to pin")
                path = repo_root() / "tests" / "adversarial" / task_id / stub
                if expect_fail:
                    with self.assertRaises(StaticCheckError):
                        validate_static_checks(path, params, build_kind="espidf")
                else:
                    validate_static_checks(path, params, build_kind="espidf")

    def test_hardened_tasks_demand_runtime_distinguishers(self):
        for task_id, level, _stub, _expect_fail in ESPIDF_STUBS:
            with self.subTest(task=task_id):
                task = load_task(task_id, platform="esp32s3_espidf", level=level)
                self.assertTrue(
                    task.simulation_variants or task.scenario or task.requires_vcd,
                    f"{task_id} has neither variants, a stimulus scenario, nor a waveform oracle",
                )


if __name__ == "__main__":
    unittest.main()

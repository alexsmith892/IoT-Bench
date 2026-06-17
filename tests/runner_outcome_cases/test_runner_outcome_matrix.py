from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.cli import build_single_task, run_single_task
from bench.config import VALIDATOR_FAMILIES, load_task
from bench.results import (
    RESULT_BC,
    RESULT_BF,
    RESULT_BY_CLASSIFICATION,
    RESULT_CF,
    RESULT_IF,
    COMPILE_FAIL,
    SIM_INFRA_FAIL,
    SOURCE_ENVIRONMENT,
    SOURCE_USER_CODE,
    STAGE_COMPILE,
    STAGE_SIM_INFRA,
)
from bench.runner import BuildSimulationError, generate_case, run_checked
from bench.validators import validate_task

from tests.runner_outcome_cases.helpers import (
    assert_payload_result,
    blink_events,
    case_paths,
    morse_sos_events,
    run_cli,
    task_config,
    write_digital_vcd,
    write_lcd_vcd,
    write_multi_vcd,
    write_pwm_vcd,
    write_serial,
    write_sketch,
)


class RunnerOutcomeMatrixTests(unittest.TestCase):
    def test_every_validator_family_has_intentional_bc_and_bf_controls(self):
        self.assertEqual(set(FAMILY_CASES), VALIDATOR_FAMILIES)

        for family, factory in FAMILY_CASES.items():
            with self.subTest(family=family, outcome="BC"), tempfile.TemporaryDirectory() as tmp:
                payload = factory(Path(tmp), passing=True)
                assert_payload_result(self, payload, RESULT_BC)

            with self.subTest(family=family, outcome="BF"), tempfile.TemporaryDirectory() as tmp:
                payload = factory(Path(tmp), passing=False)
                assert_payload_result(self, payload, RESULT_BF)

    def test_composite_failure_reports_first_failing_subcheck_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = composite_case(Path(tmp), passing=False)

        assert_payload_result(self, payload, RESULT_BF)
        checks = payload["metrics"]["checks"]
        self.assertEqual(len(checks), 1, payload)
        self.assertEqual(checks[0]["family"], "static_checks", payload)
        self.assertEqual(checks[0]["classification"], "FAIL", payload)

    def test_validate_artifacts_cli_reports_bc_and_bf_for_synthetic_waveforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task("blink_led_1hz")
            paths = generate_case(task, root=Path(tmp))
            assert paths.vcd is not None

            write_digital_vcd(paths.vcd, blink_events(0.5, cycles=6))
            payload = run_cli([
                "-m",
                "bench.cli",
                "validate-artifacts",
                "--task",
                "blink_led_1hz",
                "--case",
                str(paths.case_dir),
                "--allow-unverified-artifacts",
            ])
            assert_payload_result(self, payload, RESULT_BC)

            write_digital_vcd(paths.vcd, blink_events(0.3, cycles=6))
            payload = run_cli([
                "-m",
                "bench.cli",
                "validate-artifacts",
                "--task",
                "blink_led_1hz",
                "--case",
                str(paths.case_dir),
                "--allow-unverified-artifacts",
            ])
            assert_payload_result(self, payload, RESULT_BF)

    def test_invalid_submission_shape_is_cf_through_public_build_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("blink_led_1hz")
            paths = generate_case(task, root=root)
            submitted = root / "ambiguous-submission"
            submitted.mkdir()
            (submitted / "a.ino").write_text("void setup(){}\n", encoding="utf-8")
            (submitted / "b.ino").write_text("void loop(){}\n", encoding="utf-8")

            payload = build_single_task(
                task,
                case_dir=paths.case_dir,
                sketch_override=submitted,
                regenerate=False,
                arduino_cli="arduino-cli",
            )

        assert_payload_result(self, payload, RESULT_CF)

    def test_missing_submission_is_cf_through_public_run_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("blink_led_1hz")
            paths = generate_case(task, root=root)

            payload = run_single_task(
                task,
                case_dir=paths.case_dir,
                sketch_override=root / "does-not-exist.ino",
                use_existing_artifacts=False,
                regenerate=False,
                simulation_time_ms=None,
                arduino_cli="arduino-cli",
                wokwi_cli="wokwi-cli",
                archived_vcd=None,
            )

        assert_payload_result(self, payload, RESULT_CF)

    def test_compile_success_without_firmware_artifacts_is_if_not_cf_or_bf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("blink_led_1hz")
            paths = generate_case(task, root=root)

            with patch("bench.runner.run_checked", return_value=None):
                payload = build_single_task(
                    task,
                    case_dir=paths.case_dir,
                    sketch_override=None,
                    regenerate=False,
                    arduino_cli="arduino-cli",
                )

        assert_payload_result(self, payload, RESULT_IF)
        self.assertNotIn(payload["result"], {RESULT_CF, RESULT_BF}, payload)

    def test_build_timeout_is_if_not_cf_through_public_espidf_build_path(self):
        # A compile-stage wall-clock timeout is infrastructure (machine
        # saturation / hung tool), never proof the model's source failed to
        # compile. It must surface as IF (retryable), not CF charged to the model.
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task("blink_led_1hz", platform="esp32s3_espidf", level="level1")
            paths = generate_case(task, root=Path(tmp))
            timeout = subprocess.TimeoutExpired(cmd=["idf.py", "build"], timeout=300.0)

            with patch("bench.runner.subprocess.run", side_effect=timeout):
                payload = build_single_task(
                    task,
                    case_dir=paths.case_dir,
                    sketch_override=None,
                    regenerate=False,
                    arduino_cli="arduino-cli",
                    idf_py="idf.py",
                )

        assert_payload_result(self, payload, RESULT_IF)
        self.assertNotIn(payload["result"], {RESULT_CF, RESULT_BF}, payload)

    def test_run_checked_timeout_maps_to_infra_even_for_compile_stage(self):
        # Pins the shared helper directly with the compile-stage param set used by
        # build_espidf_case and the Zephyr compile step: a timeout there must map
        # to the infra classification (-> IF), not COMPILE_FAIL (-> CF).
        timeout = subprocess.TimeoutExpired(cmd=["west", "build"], timeout=600.0)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "bench.runner.subprocess.run", side_effect=timeout
        ):
            with self.assertRaises(BuildSimulationError) as ctx:
                run_checked(
                    ["west", "build"],
                    cwd=Path(tmp),
                    stage="zephyr compile",
                    timeout_s=600.0,
                    command_failure_classification=COMPILE_FAIL,
                    command_failure_stage=STAGE_COMPILE,
                    infra_failure_classification=SIM_INFRA_FAIL,
                    infra_failure_stage=STAGE_SIM_INFRA,
                    command_failure_source=SOURCE_USER_CODE,
                    infra_failure_source=SOURCE_ENVIRONMENT,
                )

        err = ctx.exception
        self.assertEqual(err.classification, SIM_INFRA_FAIL, err)
        self.assertEqual(err.failure_source, SOURCE_ENVIRONMENT, err)
        self.assertEqual(RESULT_BY_CLASSIFICATION[err.classification], RESULT_IF)

    def test_espidf_build_timeout_is_env_configurable_with_safe_fallback(self):
        from bench.runner import DEFAULT_ESPIDF_BUILD_TIMEOUT_S, espidf_build_timeout_s

        env = "IOTBENCH_ESPIDF_BUILD_TIMEOUT_S"
        with patch.dict("os.environ", {}, clear=False):
            for bad in ("", "not-a-number", "0", "-5"):
                with patch.dict("os.environ", {env: bad}):
                    self.assertEqual(espidf_build_timeout_s(), DEFAULT_ESPIDF_BUILD_TIMEOUT_S)
            with patch.dict("os.environ", {env: "900"}):
                self.assertEqual(espidf_build_timeout_s(), 900.0)


def payload_for(root: Path, family: str, validator: dict, *, sketch: Path | None = None, serial: Path | None = None, vcd: Path | None = None, static_checks: dict | None = None) -> dict:
    task = task_config(root, family, validator, static_checks=static_checks)
    result = validate_task(task, case_paths(root, task, sketch=sketch, serial_log=serial, vcd=vcd))
    return result.payload()


def static_checks_case(root: Path, *, passing: bool) -> dict:
    sketch = write_sketch(root, "void setup(){ Serial.begin(115200); }\nvoid loop(){ requiredToken(); }\n" if passing else "void setup(){}\nvoid loop(){}\n")
    return payload_for(
        root,
        "static_checks",
        {"family": "static_checks", "params": {"required_patterns": ["requiredToken"]}},
        sketch=sketch,
    )


def serial_regex_sequence_case(root: Path, *, passing: bool) -> dict:
    serial = write_serial(root, "alpha\nbeta\n" if passing else "beta\nalpha\n")
    return payload_for(
        root,
        "serial_regex_sequence",
        {"family": "serial_regex_sequence", "params": {"patterns": ["alpha", "beta"]}},
        serial=serial,
    )


def serial_numeric_ranges_case(root: Path, *, passing: bool) -> dict:
    serial = write_serial(root, "value 5\nvalue 10\n" if passing else "value 5\nvalue 20\n")
    return payload_for(
        root,
        "serial_numeric_ranges",
        {"family": "serial_numeric_ranges", "params": {"ranges": [[4, 6], [9, 11]]}},
        serial=serial,
    )


def bme280_environment_case(root: Path, *, passing: bool) -> dict:
    serial = write_serial(root, "Temperature: 24.6 C Humidity: 55.1 %\n" if passing else "Temperature: 24.6 C\n")
    return payload_for(
        root,
        "bme280_environment",
        {
            "family": "bme280_environment",
            "params": {"expected_temperature_c": 24.5, "expected_humidity_rh": 55.0},
        },
        serial=serial,
    )


def lcd_text_case(root: Path, *, passing: bool) -> dict:
    vcd = write_lcd_vcd(root / "lcd.vcd", "Hello World" if passing else "Goodbye")
    return payload_for(
        root,
        "lcd_text",
        {"family": "lcd_text", "params": {"expected_texts": ["Hello World"]}},
        vcd=vcd,
    )


def lcd_text_sequence_case(root: Path, *, passing: bool) -> dict:
    vcd = write_lcd_vcd(root / "lcd-sequence.vcd", "Hello World")
    frames = [{"expected_texts": ["Hello"]}, {"expected_texts": ["Hello World"]}]
    if not passing:
        frames = [{"expected_texts": ["Hello"]}, {"expected_texts": ["Missing"]}]
    return payload_for(
        root,
        "lcd_text_sequence",
        {"family": "lcd_text_sequence", "params": {"frames": frames}},
        vcd=vcd,
    )


def window_ratios_case(root: Path, *, passing: bool) -> dict:
    events = [(0.0, 0), (0.2, 1), (0.8, 0)] if passing else [(0.0, 0), (0.2, 0), (0.8, 0)]
    vcd = write_digital_vcd(root / "window.vcd", events)
    return payload_for(
        root,
        "window_ratios",
        {"family": "window_ratios", "params": {"channel": "D0", "windows": [{"start_s": 0.2, "end_s": 0.8, "ratio_range": [0.8, 1.0]}]}},
        vcd=vcd,
    )


def frequency_windows_case(root: Path, *, passing: bool) -> dict:
    vcd = write_digital_vcd(root / "frequency-window.vcd", blink_events(0.5 if passing else 0.3, cycles=6))
    return payload_for(
        root,
        "frequency_windows",
        {
            "family": "frequency_windows",
            "params": {
                "channel": "D0",
                "windows": [
                    {
                        "start_s": 0.1,
                        "end_s": 5.2,
                        "half_period_range_s": [0.475, 0.525],
                        "full_period_range_s": [0.95, 1.05],
                        "duty_cycle_range": [0.45, 0.55],
                    }
                ],
            },
        },
        vcd=vcd,
    )


def waveform_frequency_case(root: Path, *, passing: bool) -> dict:
    vcd = write_digital_vcd(root / "waveform.vcd", blink_events(0.5 if passing else 0.3, cycles=6))
    return payload_for(
        root,
        "waveform_frequency",
        {"family": "waveform_frequency", "params": {"channels": {"D0": frequency_params()}}},
        vcd=vcd,
    )


def morse_sos_case(root: Path, *, passing: bool) -> dict:
    vcd = write_digital_vcd(root / "morse.vcd", morse_sos_events(0.2, dash_units=3 if passing else 2))
    return payload_for(
        root,
        "morse_sos",
        {
            "family": "morse_sos",
            "params": {
                "channel": "D0",
                "unit_s": 0.2,
                "timing_tolerance": 0.05,
                "high_units": [1, 1, 1, 3, 3, 3, 1, 1, 1],
                "gap_units": [1, 1, 3, 1, 1, 3, 1, 1],
            },
        },
        vcd=vcd,
    )


def no_delay_static_plus_waveform_case(root: Path, *, passing: bool) -> dict:
    sketch = write_sketch(root, "void loop(){ millis(); }\n" if passing else "void loop(){ delay(500); }\n")
    vcd = write_digital_vcd(root / "no-delay.vcd", blink_events(0.5, cycles=6))
    return payload_for(
        root,
        "no_delay_static_plus_waveform",
        {"family": "no_delay_static_plus_waveform", "params": {"channels": {"D0": frequency_params()}}},
        sketch=sketch,
        vcd=vcd,
        static_checks={"forbidden_calls": ["delay", "delayMicroseconds"]},
    )


def multi_channel_frequency_case(root: Path, *, passing: bool) -> dict:
    vcd = write_multi_vcd(
        root / "multi.vcd",
        {
            "D0": blink_events(0.5, cycles=6),
            "D1": blink_events(0.25 if passing else 0.4, cycles=10),
        },
    )
    return payload_for(
        root,
        "multi_channel_frequency",
        {
            "family": "multi_channel_frequency",
            "params": {
                "channels": {
                    "D0": frequency_params(),
                    "D1": frequency_params(half=[0.225, 0.275], full=[0.45, 0.55]),
                }
            },
        },
        vcd=vcd,
    )


def pwm_breathing_case(root: Path, *, passing: bool) -> dict:
    rising = [(index + 1) / 50 for index in range(50)]
    duties = rising + list(reversed(rising)) + rising[:20] if passing else [0.5] * 120
    vcd = write_pwm_vcd(root / "pwm.vcd", duties)
    return payload_for(
        root,
        "pwm_breathing",
        {"family": "pwm_breathing", "params": {"channel": "D0", "levels": 50, "step_interval_s": 0.010, "full_period_range_s": [0.95, 1.05]}},
        vcd=vcd,
    )


def stimulus_to_output_case(root: Path, *, passing: bool) -> dict:
    events = [(0.0, 0), (0.6, 1), (1.0, 0)] if passing else [(0.0, 1), (1.0, 1)]
    vcd = write_digital_vcd(root / "stimulus.vcd", events)
    return payload_for(
        root,
        "stimulus_to_output",
        {"family": "stimulus_to_output", "params": {"channel": "D0", "active_windows_s": [[0.7, 0.9]], "inactive_windows_s": [[0.2, 0.5]]}},
        vcd=vcd,
    )


def serial_contains_on_stimulus_case(root: Path, *, passing: bool) -> dict:
    serial = write_serial(root, "Button Pressed!\n" if passing else "idle\n")
    return payload_for(
        root,
        "serial_contains_on_stimulus",
        {"family": "serial_contains_on_stimulus", "params": {"expected_texts": ["Button Pressed!"]}},
        serial=serial,
    )


def serial_count_sequence_case(root: Path, *, passing: bool) -> dict:
    serial = write_serial(root, "count: 1\ncount: 2\ncount: 3\n" if passing else "count: 1\ncount: 2\n")
    return payload_for(
        root,
        "serial_count_sequence",
        {"family": "serial_count_sequence", "params": {"expected_count": 3}},
        serial=serial,
    )


def debounce_serial_case(root: Path, *, passing: bool) -> dict:
    serial = write_serial(root, "Button Pressed!\nButton Pressed!\n" if passing else "Button Pressed!\nButton Pressed!\nButton Pressed!\n")
    return payload_for(
        root,
        "debounce_serial",
        {"family": "debounce_serial", "params": {"expected_text": "Button Pressed!", "expected_triggers": 2}},
        serial=serial,
    )


def analog_temperature_serial_case(root: Path, *, passing: bool) -> dict:
    serial = write_serial(root, "0.0\n25.0\n" if passing else "25.0\n0.0\n")
    return payload_for(
        root,
        "analog_temperature_serial",
        {"family": "analog_temperature_serial", "params": {"expected_celsius": [0.0, 25.0], "tolerance_celsius": 1.0}},
        serial=serial,
    )


def serial_observation_sequence_case(root: Path, *, passing: bool) -> dict:
    serial = write_serial(root, "Distance: 10 cm\n" if passing else "Distance: 50 cm\n")
    return payload_for(
        root,
        "serial_observation_sequence",
        {"family": "serial_observation_sequence", "params": {"observations": [{"label": "near", "patterns": ["Distance"], "numeric_ranges": [[9, 11]]}]}},
        serial=serial,
    )


def bus_activity_case(root: Path, *, passing: bool) -> dict:
    events = [(0.0, 0), (0.1, 1), (0.2, 0), (0.3, 1)] if passing else [(0.0, 0), (0.3, 0)]
    vcd = write_digital_vcd(root / "bus.vcd", events)
    return payload_for(
        root,
        "bus_activity",
        {"family": "bus_activity", "params": {"bus": "i2c", "pins": ["D0"], "min_transitions": 2}},
        vcd=vcd,
    )


def composite_case(root: Path, *, passing: bool) -> dict:
    sketch = write_sketch(root, "void loop(){ requiredToken(); }\n" if passing else "void loop(){}\n")
    serial = write_serial(root, "1\n2\n3\n")
    return payload_for(
        root,
        "composite",
        {
            "family": "composite",
            "checks": [
                {"family": "static_checks", "params": {"required_patterns": ["requiredToken"]}},
                {"family": "serial_count_sequence", "params": {"expected_count": 3}},
            ],
        },
        sketch=sketch,
        serial=serial,
    )


def frequency_params(*, half: list[float] | None = None, full: list[float] | None = None) -> dict:
    return {
        "min_valid_cycles_after_startup": 4,
        "half_period_range_s": half or [0.475, 0.525],
        "full_period_range_s": full or [0.95, 1.05],
        "duty_cycle_range": [0.45, 0.55],
    }


FAMILY_CASES = {
    "composite": composite_case,
    "static_checks": static_checks_case,
    "serial_regex_sequence": serial_regex_sequence_case,
    "serial_numeric_ranges": serial_numeric_ranges_case,
    "bme280_environment": bme280_environment_case,
    "lcd_text": lcd_text_case,
    "window_ratios": window_ratios_case,
    "frequency_windows": frequency_windows_case,
    "waveform_frequency": waveform_frequency_case,
    "morse_sos": morse_sos_case,
    "no_delay_static_plus_waveform": no_delay_static_plus_waveform_case,
    "multi_channel_frequency": multi_channel_frequency_case,
    "pwm_breathing": pwm_breathing_case,
    "stimulus_to_output": stimulus_to_output_case,
    "serial_contains_on_stimulus": serial_contains_on_stimulus_case,
    "serial_count_sequence": serial_count_sequence_case,
    "debounce_serial": debounce_serial_case,
    "analog_temperature_serial": analog_temperature_serial_case,
    "serial_observation_sequence": serial_observation_sequence_case,
    "bus_activity": bus_activity_case,
    "lcd_text_sequence": lcd_text_sequence_case,
}


if __name__ == "__main__":
    unittest.main()

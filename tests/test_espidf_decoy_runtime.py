"""Runtime BF expectations for ESP32-S3 submissions.

The static-gate expectations for the ESP-IDF adversarial corpus live in
``tests.test_adversarial_static``. Those decoys *pass* the static gate on
purpose; their rejection is supposed to happen at the behavior oracle. This
module pins that second half offline and deterministically, and additionally
closes the runtime side of tasks that previously had no adversarial coverage at
all: for each task, generate the real case, feed a capture that models a cheat
(active but fixed/wrong in the dimension the oracle measures, or — for
distinct-variant tasks — identical across variants), and assert the task's
*real* validator params classify it as a behavior failure (FAIL -> BF).

This guards against a whole class of benchmark bugs the per-family matrix in
``tests.runner_outcome_cases`` cannot catch: a specific task whose committed
validator params are vacuous (empty observations, a ratio band that accepts
everything, a missing ``expected_texts``), which would silently let a hardcoded
submission score BC. The genuine fixed-but-active decoys are additionally
exercised end to end by the opt-in live Wokwi runs.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench.config import load_task
from bench.runner import generate_case, paths_for_variant, variant_id

from tests.runner_outcome_cases.helpers import write_multi_vcd
from tests.validator_test_utils import assert_classification, validate_artifacts_args


# (task_id, level). The ESP-IDF decoys that pass the static gate
# (expect_fail=False in tests.test_adversarial_static.ESPIDF_STUBS) and so must
# be rejected at runtime instead.
DECOY_TASKS = [
    ("dht11_read", "level2"),
    ("ds1307_rtc", "level2"),
    ("parking_sensor", "level2"),
    ("reverse_parking_sensor", "level2"),
    ("rotary_encoder", "level2"),
    ("clap_switch", "level2"),
    ("photoresistor_nightlight", "level2"),
    ("dht11_read_button_display", "level3"),
    ("lcd1602_auto_brightness_control", "level3"),
    ("mpu6050_read_button_display", "level3"),
    ("mpu6050_read_periodic_display", "level3"),
    ("buzzer_toggle_led_freq", "level3"),
    ("reaction_timer_display", "level3"),
    ("buzzer_laser_tripwire", "level3"),
    ("joystick_buzzer_pitch", "level3"),
    ("safebox", "level3"),
    ("safebox_display", "level3"),
    ("step_counter_print", "level3"),
]

# ESP32 tasks that previously had no committed adversarial coverage at all.
# Pinning a non-conforming capture -> BF here closes that gap (Phase 2B) without
# needing a bespoke .c stub per task: it proves each task's real oracle params
# are not vacuous. The waveform-only Level 1 tasks are inherently un-hardcodable
# through serial, so a single wrong-waveform expectation is sufficient.
UNCOVERED_TASKS = [
    ("blink_led_morse_code", "level1"),
    ("blink_two_leds", "level1"),
    ("breathing_led", "level1"),
    ("button_status_display", "level1"),
    ("buzzer_button", "level1"),
    ("buzzer_doorbell", "level1"),
    ("hcsr501_motion_alarm", "level2"),
    ("tilt_detection_alarm", "level2"),
    ("mpu6050_read_spi", "level2"),
    ("sensor_water_level_display", "level3"),
]

RUNTIME_BF_TASKS = DECOY_TASKS + UNCOVERED_TASKS

VCD_FAMILIES = {
    "window_ratios",
    "frequency_windows",
    "stimulus_to_output",
    "bus_activity",
    "lcd_text",
    "lcd_text_sequence",
    "waveform_frequency",
    "multi_channel_frequency",
    "no_delay_static_plus_waveform",
    "pwm_breathing",
    "morse_sos",
}


def first_runtime_check(task) -> dict:
    validator = task.validator
    if validator.get("family") == "composite":
        for check in validator.get("checks", []):
            if check.get("family") != "static_checks":
                return check
        raise AssertionError(f"{task.task_id}: composite has no runtime check")
    return validator


def square_wave(*, duty: float, period: float, span: float) -> list[tuple[int, int]]:
    """A clean square wave at a fixed (wrong) frequency / duty across the trace."""
    events: list[tuple[float, int]] = []
    base = 0.0
    while base < span:
        events.append((round(base, 9), 1))
        events.append((round(base + duty * period, 9), 0))
        base += period
    return events


def violating_ratio_duty(bounds: list[float]) -> float:
    # in_range() only reads bounds[0]/bounds[1], so a value outside that span is
    # rejected regardless of any further bands.
    low, high = float(bounds[0]), float(bounds[1])
    if high < 1.0:
        return (high + 1.0) / 2.0
    if low > 0.0:
        return low / 2.0
    raise AssertionError(f"ratio band {bounds} accepts every ratio (vacuous oracle)")


def write_blank_lcd_vcd(path: Path, *, signals: int = 10) -> None:
    """A parseable LCD bus that carries no valid frame.

    Declares a superset of data/control lines (D0..D9) so any task's LCD signal
    map resolves (the decoder raises -> IF if a mapped signal is absent), while
    the toggles never latch the expected reading, so the oracle returns FAIL.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    names = [f"D{i}" for i in range(signals)]
    symbols = [chr(33 + i) for i in range(signals)]
    lines = [
        "$version synthetic decoy lcd $end",
        "$timescale 1ns $end",
        "$scope module logic $end",
        *[f"$var wire 1 {sym} {name} $end" for sym, name in zip(symbols, names)],
        "$upscope $end",
        "$enddefinitions $end",
        "#0",
        *[f"0{sym}" for sym in symbols],
    ]
    # A few harmless toggles so every line has transitions but no nibble latches
    # into the expected text.
    for step, t_ns in enumerate((1000, 2000, 3000, 4000), start=1):
        lines.append(f"#{t_ns}")
        sym = symbols[step % signals]
        lines.append(f"{step % 2}{sym}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_cheat_vcd(path: Path, check: dict) -> None:
    family = check.get("family")
    params = check.get("params", {})
    channel = params.get("channel", "D0")

    if family in {"lcd_text", "lcd_text_sequence"}:
        # A fixed frame that does not carry the expected reading.
        write_blank_lcd_vcd(path)
        return

    signals: dict[str, list[tuple]] = {}
    if family == "window_ratios":
        window = (params.get("windows") or [{}])[0]
        end = float(window.get("end_s", 1.2))
        duty = violating_ratio_duty(window.get("ratio_range", [0.0, 1.0]))
        signals[channel] = square_wave(duty=duty, period=0.02, span=end + 0.2)
    elif family == "frequency_windows":
        window = (params.get("windows") or [{}])[0]
        end = float(window.get("end_s", 1.2))
        signals[channel] = square_wave(duty=0.5, period=0.1, span=end + 0.3)
    elif family in {
        "waveform_frequency",
        "multi_channel_frequency",
        "no_delay_static_plus_waveform",
    }:
        # Active, but every LED runs at the same fixed (far too slow) frequency.
        channels = list((params.get("channels") or {}).keys()) or ["D0", "D1"]
        for ch in channels:
            signals[ch] = square_wave(duty=0.5, period=0.1, span=6.0)
    elif family == "morse_sos":
        # A plain square wave never matches the SOS unit timing.
        signals[channel] = square_wave(duty=0.5, period=0.5, span=8.0)
    elif family == "pwm_breathing":
        # A fixed duty is not a rising/falling breathing ramp.
        signals[channel] = square_wave(duty=0.5, period=0.001, span=2.0)
    elif family == "stimulus_to_output":
        # Stuck asserted: passes the active window but fails the inactive one.
        signals[channel] = [(0, 1)]
    elif family == "bus_activity":
        # No bus traffic: too few transitions.
        for pin in params.get("pins", ["D1"]):
            signals[str(pin)] = [(0, 0)]
    else:
        raise AssertionError(f"no VCD cheat builder for family {family}")

    write_multi_vcd(path, signals)


def write_cheat_serial(path: Path) -> None:
    # Boots and prints something, but never the expected (stimulus-correlated)
    # observation/count/pattern.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("boot\nready\n", encoding="utf-8")


class EspIdfDecoyRuntimeTests(unittest.TestCase):
    def test_decoys_are_rejected_at_runtime(self):
        for task_id, level in RUNTIME_BF_TASKS:
            with self.subTest(task=task_id):
                self._assert_runtime_fail(task_id, level)

    def _assert_runtime_fail(self, task_id: str, level: str) -> None:
        task = load_task(task_id, platform="esp32s3_espidf", level=level)
        check = first_runtime_check(task)
        is_vcd = check.get("family") in VCD_FAMILIES

        with tempfile.TemporaryDirectory() as tmp:
            paths = generate_case(task, root=Path(tmp))

            targets = []
            if task.simulation_variants:
                for variant in task.simulation_variants:
                    targets.append(paths_for_variant(paths, variant_id(variant), variant))
            else:
                targets.append(paths)

            for target in targets:
                if is_vcd:
                    self.assertIsNotNone(target.vcd, f"{task_id}: expected a VCD artifact")
                    write_cheat_vcd(target.vcd, check)
                else:
                    self.assertIsNotNone(
                        target.serial_log, f"{task_id}: expected a serial artifact"
                    )
                    write_cheat_serial(target.serial_log)
                # Some oracles declare both a serial and a VCD artifact (e.g. a
                # serial reading plus an SPI/I2C bus-activity check). The first
                # runtime check decides the FAIL, but every declared artifact must
                # exist or the pre-validation step returns IF, so fill the other
                # modality with a parseable placeholder.
                if not is_vcd and target.vcd is not None:
                    write_multi_vcd(target.vcd, {"D0": [(0, 0), (0.001, 1), (0.002, 0)]})
                if is_vcd and target.serial_log is not None:
                    write_cheat_serial(target.serial_log)

            assert_classification(
                self,
                validate_artifacts_args(task_id, paths.case_dir)
                + ["--platform", "esp32s3_espidf", "--level", level],
                "FAIL",
            )


if __name__ == "__main__":
    unittest.main()

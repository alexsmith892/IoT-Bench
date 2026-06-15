import tempfile
import unittest
from pathlib import Path

from tests.validator_test_utils import (
    assert_classification,
    make_case,
    update_case_vcd,
    validate_artifacts_args,
    write_digital_vcd,
    write_pwm_vcd,
)
from bench.vcd import VcdParseError, build_segments, parse_vcd_signal


class BreathingLedValidatorTests(unittest.TestCase):
    def test_missing_vcd_is_sim_output_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "breathing", "breathing_led")
            update_case_vcd(case_dir, case_dir / "artifacts" / "logic" / "missing.vcd")

            assert_classification(
                self,
                validate_artifacts_args("breathing_led", case_dir),
                "SIM_OUTPUT_FAIL",
            )

    def test_flat_pwm_duty_is_behavior_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "breathing", "breathing_led")
            vcd = case_dir / "artifacts" / "logic" / "flat-duty.vcd"
            write_pwm_vcd(vcd, [0.50] * 120)
            update_case_vcd(case_dir, vcd)

            assert_classification(
                self,
                validate_artifacts_args("breathing_led", case_dir),
                "FAIL",
            )

    def test_valid_breathing_pwm_sequence_is_behavior_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "breathing", "breathing_led")
            vcd = case_dir / "artifacts" / "logic" / "correct.vcd"
            rising = [(index + 1) / 50 for index in range(50)]
            write_pwm_vcd(vcd, rising + list(reversed(rising)) + rising[:20])
            update_case_vcd(case_dir, vcd)

            assert_classification(
                self,
                validate_artifacts_args("breathing_led", case_dir),
                "PASS",
            )

    def test_same_timestamp_edges_are_collapsed_before_segment_building(self):
        with tempfile.TemporaryDirectory() as tmp:
            vcd = Path(tmp) / "same-timestamp.vcd"
            write_digital_vcd(
                vcd,
                [
                    (0.0, 0),
                    (0.001, 1),
                    (0.001, 0),
                    (0.002, 1),
                    (0.003, 0),
                ],
            )

            events = parse_vcd_signal(vcd)
            build_segments(events)

            self.assertEqual([(event.timestamp_s, event.value) for event in events], [(0.0, 0), (0.002, 1), (0.003, 0)])

    def test_decreasing_vcd_timestamps_still_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            vcd = Path(tmp) / "decreasing.vcd"
            write_digital_vcd(vcd, [(0.0, 0), (0.002, 1), (0.001, 0)])

            with self.assertRaises(VcdParseError):
                parse_vcd_signal(vcd)


if __name__ == "__main__":
    unittest.main()

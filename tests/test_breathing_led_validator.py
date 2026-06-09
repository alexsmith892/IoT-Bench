import tempfile
import unittest
from pathlib import Path

from tests.validator_test_utils import (
    assert_classification,
    make_case,
    update_case_vcd,
    write_pwm_vcd,
)


class BreathingLedValidatorTests(unittest.TestCase):
    def test_missing_vcd_is_sim_output_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "breathing", "breathing_led")
            update_case_vcd(case_dir, case_dir / "artifacts" / "logic" / "missing.vcd")

            assert_classification(
                self,
                ["tools/test_breathing_led.py", "--use-existing-vcd", "--case", str(case_dir)],
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
                ["tools/test_breathing_led.py", "--use-existing-vcd", "--case", str(case_dir)],
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
                ["tools/test_breathing_led.py", "--use-existing-vcd", "--case", str(case_dir)],
                "PASS",
            )


if __name__ == "__main__":
    unittest.main()

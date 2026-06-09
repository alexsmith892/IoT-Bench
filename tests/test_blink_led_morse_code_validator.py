import tempfile
import unittest
from pathlib import Path

from tests.validator_test_utils import (
    assert_classification,
    make_case,
    morse_sos_events,
    update_case_vcd,
    validate_artifacts_args,
    write_digital_vcd,
)


class BlinkLedMorseCodeValidatorTests(unittest.TestCase):
    def test_missing_vcd_is_sim_output_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "morse", "blink_led_morse_code")
            update_case_vcd(case_dir, case_dir / "artifacts" / "logic" / "missing.vcd")

            assert_classification(
                self,
                validate_artifacts_args("blink_led_morse_code", case_dir),
                "SIM_OUTPUT_FAIL",
            )

    def test_wrong_dash_duration_is_behavior_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "morse", "blink_led_morse_code")
            vcd = case_dir / "artifacts" / "logic" / "wrong-morse.vcd"
            write_digital_vcd(vcd, morse_sos_events(unit_s=0.2, dash_units=2))
            update_case_vcd(case_dir, vcd)

            assert_classification(
                self,
                validate_artifacts_args("blink_led_morse_code", case_dir),
                "FAIL",
            )

    def test_valid_sos_sequence_is_behavior_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "morse", "blink_led_morse_code")
            vcd = case_dir / "artifacts" / "logic" / "correct.vcd"
            write_digital_vcd(vcd, morse_sos_events(unit_s=0.2, dash_units=3))
            update_case_vcd(case_dir, vcd)

            assert_classification(
                self,
                validate_artifacts_args("blink_led_morse_code", case_dir),
                "PASS",
            )


if __name__ == "__main__":
    unittest.main()

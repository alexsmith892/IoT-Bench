import tempfile
import unittest
from pathlib import Path

from tests.validator_test_utils import (
    assert_classification,
    blink_events,
    make_case,
    update_case_vcd,
    validate_artifacts_args,
    write_digital_vcd,
    write_sketch,
)


class BlinkLedNoDelayValidatorTests(unittest.TestCase):
    def test_missing_vcd_is_sim_output_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "no-delay", "blink_led_no_delay")
            update_case_vcd(case_dir, case_dir / "artifacts" / "logic" / "missing.vcd")

            assert_classification(
                self,
                validate_artifacts_args("blink_led_no_delay", case_dir),
                "SIM_OUTPUT_FAIL",
            )

    def test_wrong_frequency_is_behavior_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "no-delay", "blink_led_no_delay")
            vcd = case_dir / "artifacts" / "logic" / "wrong-frequency.vcd"
            write_digital_vcd(vcd, blink_events(half_period_s=0.300, cycles=6))
            update_case_vcd(case_dir, vcd)

            assert_classification(
                self,
                validate_artifacts_args("blink_led_no_delay", case_dir),
                "FAIL",
            )

    def test_blocking_delay_source_is_behavior_failure_even_with_valid_waveform(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "blocking-no-delay", "blink_led_no_delay")
            write_sketch(case_dir, "blink_led_no_delay", "void loop(){ delay(500); }\n")
            vcd = case_dir / "artifacts" / "logic" / "good-waveform.vcd"
            write_digital_vcd(vcd, blink_events(half_period_s=0.500, cycles=6))
            update_case_vcd(case_dir, vcd)

            assert_classification(
                self,
                validate_artifacts_args("blink_led_no_delay", case_dir),
                "FAIL",
            )

    def test_valid_nonblocking_waveform_is_behavior_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "no-delay", "blink_led_no_delay")
            vcd = case_dir / "artifacts" / "logic" / "correct.vcd"
            write_digital_vcd(vcd, blink_events(half_period_s=0.500, cycles=6))
            update_case_vcd(case_dir, vcd)

            assert_classification(
                self,
                validate_artifacts_args("blink_led_no_delay", case_dir),
                "PASS",
            )


if __name__ == "__main__":
    unittest.main()

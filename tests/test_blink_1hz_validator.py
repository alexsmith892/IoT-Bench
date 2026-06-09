import tempfile
import unittest
from pathlib import Path

from tests.validator_test_utils import (
    assert_classification,
    blink_events,
    make_case,
    update_case_vcd,
    write_digital_vcd,
)


class Blink1HzValidatorTests(unittest.TestCase):
    def test_failed_compile_is_compile_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "compile-fail", "blink_1hz")

            assert_classification(
                self,
                [
                    "tools/blink_vcd_harness.py",
                    "--case",
                    str(case_dir),
                    "--arduino-cli",
                    "python",
                ],
                "COMPILE_FAIL",
            )

    def test_missing_case_manifest_is_sim_infra_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "missing-manifest"
            case_dir.mkdir()

            assert_classification(
                self,
                ["tools/blink_vcd_harness.py", "--case", str(case_dir)],
                "SIM_INFRA_FAIL",
            )

    def test_missing_vcd_is_sim_output_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "blink-1hz", "blink_1hz")
            update_case_vcd(case_dir, case_dir / "artifacts" / "logic" / "missing.vcd")

            assert_classification(
                self,
                ["tools/blink_vcd_harness.py", "--use-existing-vcd", "--case", str(case_dir)],
                "SIM_OUTPUT_FAIL",
            )

    def test_wrong_frequency_is_behavior_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "blink-1hz", "blink_1hz")
            vcd = case_dir / "artifacts" / "logic" / "wrong-frequency.vcd"
            write_digital_vcd(vcd, blink_events(half_period_s=0.300, cycles=6))
            update_case_vcd(case_dir, vcd)

            assert_classification(
                self,
                ["tools/blink_vcd_harness.py", "--use-existing-vcd", "--case", str(case_dir)],
                "FAIL",
            )

    def test_valid_one_hz_waveform_is_behavior_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "blink-1hz", "blink_1hz")
            vcd = case_dir / "artifacts" / "logic" / "correct.vcd"
            write_digital_vcd(vcd, blink_events(half_period_s=0.500, cycles=6))
            update_case_vcd(case_dir, vcd)

            assert_classification(
                self,
                ["tools/blink_vcd_harness.py", "--use-existing-vcd", "--case", str(case_dir)],
                "PASS",
            )

    def test_latest_archived_vcd_can_be_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = make_case(Path(tmp), "blink-1hz", "blink_1hz")
            archive_dir = case_dir / "artifacts" / "archive" / "vcd"
            vcd = archive_dir / "blink-1hz__20260608T110000000000Z__wokwi.vcd"
            write_digital_vcd(vcd, blink_events(half_period_s=0.500, cycles=6))

            assert_classification(
                self,
                [
                    "tools/blink_vcd_harness.py",
                    "--case",
                    str(case_dir),
                    "--archived-vcd",
                    "latest",
                ],
                "PASS",
            )


if __name__ == "__main__":
    unittest.main()

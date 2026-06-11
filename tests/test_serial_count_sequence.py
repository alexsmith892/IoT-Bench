"""serial_count_sequence must reject under-specified or hardcoded counter output."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench.config import TaskConfig
from bench.runner import CasePaths
from bench.serial import exact_count_sequence, monotonic_counter_reaches
from bench.validators import validate_task


def count_task(case_dir: Path, params: dict) -> tuple[TaskConfig, CasePaths]:
    task = TaskConfig(
        path=case_dir / "task.yaml",
        data={
            "task_id": "button_status_count",
            "fixture": {"family": "button_serial", "pins": {"button": "2"}},
            "validator": {"family": "serial_count_sequence", "params": params},
            "case": {"id": case_dir.name, "sketch_name": "button_status_count"},
        },
    )
    paths = CasePaths(
        task_id="button_status_count",
        case_id=case_dir.name,
        case_dir=case_dir,
        sketch=case_dir / "sketch" / "button_status_count",
        diagram=case_dir / "diagram.json",
        wokwi_toml=case_dir / "wokwi.toml",
        build_dir=case_dir / "artifacts" / "build",
        fqbn="arduino:avr:mega",
        serial_log=case_dir / "artifacts" / "serial" / "serial.log",
    )
    return task, paths


def classify(serial_text: str, params: dict) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        case_dir = Path(tmp)
        task, paths = count_task(case_dir, params)
        assert paths.serial_log is not None
        paths.serial_log.parent.mkdir(parents=True)
        paths.serial_log.write_text(serial_text, encoding="utf-8")
        return validate_task(task, paths).classification


EXACT = {"expected_count": 3, "match_mode": "exact_sequence"}


class ExactCountSequenceTests(unittest.TestCase):
    def test_exact_sequence_passes(self):
        self.assertEqual(classify("1\n2\n3\n", EXACT), "PASS")

    def test_labeled_exact_sequence_passes(self):
        self.assertEqual(classify("Count: 1\nCount: 2\nCount: 3\n", EXACT), "PASS")

    def test_single_hardcoded_value_fails(self):
        self.assertEqual(classify("999\n", EXACT), "FAIL")
        self.assertEqual(classify("3\n", EXACT), "FAIL")

    def test_skipped_count_fails(self):
        self.assertEqual(classify("1\n3\n", EXACT), "FAIL")

    def test_extra_trailing_count_fails(self):
        self.assertEqual(classify("1\n2\n3\n4\n", EXACT), "FAIL")

    def test_duplicates_fail_by_default(self):
        self.assertEqual(classify("1\n1\n2\n3\n", EXACT), "FAIL")

    def test_duplicates_pass_with_allow_repeats(self):
        params = {**EXACT, "allow_repeats": True}
        self.assertEqual(classify("1\n1\n2\n2\n3\n", params), "PASS")
        # Non-consecutive repeats are still rejected (counter went backwards).
        self.assertEqual(classify("1\n2\n1\n3\n", params), "FAIL")

    def test_default_mode_remains_monotonic_reaches(self):
        params = {"expected_count": 3}
        self.assertEqual(classify("1\n2\n3\n", params), "PASS")
        self.assertEqual(classify("999\n", params), "PASS")  # documented legacy laxness
        self.assertEqual(classify("3\n2\n", params), "FAIL")


class SerialHelperTests(unittest.TestCase):
    def test_exact_count_sequence_helper(self):
        self.assertTrue(exact_count_sequence([1, 2, 3], 3))
        self.assertFalse(exact_count_sequence([999], 3))
        self.assertFalse(exact_count_sequence([], 3))
        self.assertFalse(exact_count_sequence([1, 2], 3))
        self.assertTrue(exact_count_sequence([1, 1, 2, 3], 3, allow_repeats=True))

    def test_monotonic_counter_reaches_unchanged(self):
        self.assertTrue(monotonic_counter_reaches([1, 2, 3], 3))
        self.assertTrue(monotonic_counter_reaches([999], 3))
        self.assertFalse(monotonic_counter_reaches([3, 2], 3))


if __name__ == "__main__":
    unittest.main()

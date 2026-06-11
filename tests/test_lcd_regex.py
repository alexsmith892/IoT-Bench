"""expected_regexps support in lcd_text and lcd_text_sequence oracles."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from bench.config import ConfigError, TaskConfig, validate_lcd_text_sequence_config
from bench.lcd1602 import LcdFrame, LcdTimedFrame, frame_matches_regex
from bench.results import FAIL, PASS
from bench.runner import CasePaths
from bench.validators import validate_lcd_text, validate_lcd_text_sequence


def frame(line0: str, line1: str = "") -> LcdFrame:
    return LcdFrame(rows=[line0.ljust(16), line1.ljust(16)])


def lcd_task(validator: dict) -> TaskConfig:
    return TaskConfig(
        path=Path("task.yaml"),
        data={
            "task_id": "stub",
            "fixture": {"family": "composite", "components": []},
            "validator": validator,
            "case": {"id": "stub-case", "sketch_name": "stub"},
        },
    )


def lcd_paths() -> CasePaths:
    case_dir = Path("case")
    return CasePaths(
        task_id="stub",
        case_id="stub-case",
        case_dir=case_dir,
        sketch=case_dir / "sketch" / "stub",
        diagram=case_dir / "diagram.json",
        wokwi_toml=case_dir / "wokwi.toml",
        build_dir=case_dir / "artifacts" / "build",
        fqbn="arduino:avr:mega",
        vcd=case_dir / "artifacts" / "logic" / "wokwi.vcd",
    )


class FrameMatchesRegexTests(unittest.TestCase):
    def test_matches_numeric_content(self):
        self.assertTrue(frame_matches_regex(frame("Temp: 24 C"), r"Temp:\s*24"))
        self.assertFalse(frame_matches_regex(frame("Temp: 31 C"), r"Temp:\s*24"))

    def test_matches_across_rows_via_normalized_text(self):
        two_row = frame("Reaction:", "342 ms")
        self.assertTrue(frame_matches_regex(two_row, r"\b3[0-9]{2} ms"))
        self.assertFalse(frame_matches_regex(two_row, r"\b9[0-9]{2} ms"))


class LcdTextRegexValidatorTests(unittest.TestCase):
    def test_lcd_text_regex_pass_and_fail(self):
        task = lcd_task(
            {
                "family": "lcd_text",
                "params": {"expected_texts": ["Temp:"], "expected_regexps": [r"Temp:\s*24"]},
            }
        )
        with patch("bench.validators.decode_lcd1602_vcd", return_value=frame("Temp: 24 C")):
            self.assertEqual(validate_lcd_text(task, lcd_paths()).classification, PASS)
        with patch("bench.validators.decode_lcd1602_vcd", return_value=frame("Temp: 31 C")):
            result = validate_lcd_text(task, lcd_paths())
        self.assertEqual(result.classification, FAIL)
        self.assertIn("pattern", result.reason)

    def test_lcd_text_sequence_regex_per_frame(self):
        task = lcd_task(
            {
                "family": "lcd_text_sequence",
                "params": {
                    "frames": [
                        {"expected_regexps": [r"Temp:\s*24"]},
                        {"expected_regexps": [r"Temp:\s*31"], "start_s": 0.5},
                    ]
                },
            }
        )
        good = [
            LcdTimedFrame(0.2, frame("Temp: 24 C")),
            LcdTimedFrame(0.8, frame("Temp: 31 C")),
        ]
        constant = [
            LcdTimedFrame(0.2, frame("Temp: 24 C")),
            LcdTimedFrame(0.8, frame("Temp: 24 C")),
        ]
        with patch("bench.validators.decode_lcd1602_vcd_frames", return_value=good):
            self.assertEqual(validate_lcd_text_sequence(task, lcd_paths()).classification, PASS)
        with patch("bench.validators.decode_lcd1602_vcd_frames", return_value=constant):
            self.assertEqual(validate_lcd_text_sequence(task, lcd_paths()).classification, FAIL)


class LcdSequenceConfigTests(unittest.TestCase):
    def test_regex_only_frames_accepted(self):
        task = lcd_task({"family": "lcd_text_sequence", "params": {}})
        validate_lcd_text_sequence_config(task, {"frames": [{"expected_regexps": [r"\d+ ms"]}]})

    def test_frame_without_texts_or_regexps_rejected(self):
        task = lcd_task({"family": "lcd_text_sequence", "params": {}})
        with self.assertRaises(ConfigError):
            validate_lcd_text_sequence_config(task, {"frames": [{}]})

    def test_invalid_regex_rejected(self):
        task = lcd_task({"family": "lcd_text_sequence", "params": {}})
        with self.assertRaises(ConfigError) as ctx:
            validate_lcd_text_sequence_config(task, {"frames": [{"expected_regexps": ["("]}]})
        self.assertIn("invalid", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

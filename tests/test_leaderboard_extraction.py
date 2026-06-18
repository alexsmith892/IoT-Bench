import tempfile
import unittest
from pathlib import Path

from bench.config import load_task
from bench.leaderboard.extraction import extract_arduino_source, extract_c_source, extract_to_source


GOOD = "void setup() { pinMode(13, OUTPUT); }\nvoid loop() { digitalWrite(13, HIGH); }\n"


class LeaderboardExtractionTests(unittest.TestCase):
    def test_raw_sketch(self):
        self.assertEqual(extract_arduino_source(GOOD), GOOD.strip())

    def test_fenced_sketch(self):
        self.assertEqual(extract_arduino_source(f"```cpp\n{GOOD}```"), GOOD.strip())

    def test_mislabeled_fence_is_accepted_by_content(self):
        self.assertEqual(extract_arduino_source(f"```python\n{GOOD}```"), GOOD.strip())

    def test_empty_response_fails_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = extract_to_source(load_task("blink_led_1hz"), "", Path(tmp))

        self.assertFalse(result.ok)
        self.assertEqual(result.result["result"], "CF")
        self.assertEqual(result.result["failure_stage"], "format")
        self.assertEqual(result.metadata["candidate_fence_count"], 0)
        self.assertIn("empty", result.metadata["failure_reason"])

    def test_multi_file_response_fails(self):
        response = f"```cpp\n{GOOD}```\n```cpp\n{GOOD}```"
        self.assertIsNone(extract_arduino_source(response))

    def test_single_c_source_for_future_platforms(self):
        source = "#include <stdio.h>\nvoid app_main(void) {}\n"

        self.assertEqual(extract_c_source(f"```c\n{source}```"), source.strip())
        self.assertIsNone(extract_c_source(f"```c\n{source}```\n```c\n{source}```"))

    def test_extraction_metadata_records_chosen_fence(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = extract_to_source(load_task("blink_led_1hz"), f"```cpp\n{GOOD}```", Path(tmp))

        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["chosen_fence_language"], "cpp")
        self.assertEqual(result.metadata["candidate_fence_count"], 1)
        self.assertIsNone(result.metadata["failure_reason"])

    def test_multiple_source_fences_metadata_records_failure(self):
        response = f"```cpp\n{GOOD}```\n```cpp\n{GOOD}```"
        with tempfile.TemporaryDirectory() as tmp:
            result = extract_to_source(load_task("blink_led_1hz"), response, Path(tmp))

        self.assertFalse(result.ok)
        self.assertEqual(result.result["failure_stage"], "format")
        self.assertEqual(result.metadata["candidate_fence_count"], 2)
        self.assertIn("multiple", result.metadata["failure_reason"])


if __name__ == "__main__":
    unittest.main()

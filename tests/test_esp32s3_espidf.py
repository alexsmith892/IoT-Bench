from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench.cli import parse_args, submission_path_for_task
from bench.config import board_profile_for_platform, iter_tasks, load_task
from bench.runner import generate_case, normalize_sketch_override
from bench.validators import position_to_tmp36_celsius


ESP32S3_LEVEL1_TASKS = {
    "blink_led_1hz",
    "blink_led_morse_code",
    "blink_led_no_delay",
    "blink_two_leds",
    "buzzer_doorbell",
    "buzzer_button",
    "button_status_display",
    "button_status_count",
    "button_press_debounce",
    "breathing_led",
    "sensor_pir_human_motion",
    "tmp36_read",
}


class Esp32S3EspIdfProfileTests(unittest.TestCase):
    def test_profile_uses_espidf_board_and_firmware_contract(self):
        profile = board_profile_for_platform("esp32s3_espidf")

        self.assertEqual(profile.board_type, "board-esp32-s3-devkitc-1")
        self.assertEqual(profile.part_id, "esp")
        self.assertEqual(profile.build_kind, "espidf")
        self.assertEqual(profile.idf_target, "esp32s3")
        self.assertEqual(profile.firmware_kind, "espidf_flasher_args")
        self.assertEqual(profile.voltage, 3.3)
        self.assertEqual(profile.adc_max, 4095)
        self.assertEqual(profile.power_pin, "3V3")
        self.assertEqual(profile.ground_pin, "GND.1")
        self.assertEqual(profile.default_pins["led"], "10")
        self.assertEqual(profile.default_pins["led2"], "11")


class Esp32S3EspIdfTaskTests(unittest.TestCase):
    def test_all_upstream_level1_tasks_load_and_have_prompts(self):
        tasks = list(iter_tasks(platform="esp32s3_espidf", level="level1"))

        self.assertEqual({task.task_id for task in tasks}, ESP32S3_LEVEL1_TASKS)
        for task in tasks:
            with self.subTest(task=task.task_id):
                self.assertTrue(task.prompt_path.exists())
                self.assertTrue(task.prompt_text.strip())
                self.assertTrue(task.prompt_text.endswith("\n"))

    def test_generated_cases_use_espidf_layout_and_esp32s3_diagrams(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for task in iter_tasks(platform="esp32s3_espidf", level="level1"):
                with self.subTest(task=task.task_id):
                    paths = generate_case(task, root=root)
                    diagram = paths.diagram.read_text(encoding="utf-8")
                    wokwi = paths.wokwi_toml.read_text(encoding="utf-8")

                    self.assertTrue((paths.sketch / "CMakeLists.txt").exists())
                    self.assertTrue((paths.sketch / "main" / "CMakeLists.txt").exists())
                    self.assertTrue((paths.sketch / "main" / "main.c").exists())
                    self.assertTrue((paths.sketch / "sdkconfig.defaults").exists())
                    self.assertFalse(list(paths.sketch.rglob("*.ino")))
                    self.assertIn("board-esp32-s3-devkitc-1", diagram)
                    self.assertIn('"id": "esp"', diagram)
                    self.assertIn("esp:", diagram)
                    self.assertNotIn("mega:", diagram)
                    self.assertIn("firmware = 'artifacts/build/flasher_args.json'", wokwi)
                    self.assertIn(f"elf = 'artifacts/build/{task.sketch_name}.elf'", wokwi)

    def test_tmp36_config_uses_3v3_adc_semantics(self):
        task = load_task("tmp36_read", platform="esp32s3_espidf")
        params = task.validator_params()

        self.assertEqual(params["expected_celsius"], [-17.0, -0.5])
        self.assertAlmostEqual(position_to_tmp36_celsius(0.10, voltage=task.board_profile.voltage), -17.0)
        self.assertAlmostEqual(position_to_tmp36_celsius(0.15, voltage=task.board_profile.voltage), -0.5)

    def test_generated_reference_source_is_espidf_not_arduino(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task("tmp36_read", platform="esp32s3_espidf")
            paths = generate_case(task, root=Path(tmp))
            source = (paths.sketch / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("void app_main(void)", source)
        self.assertIn("adc_oneshot", source)
        self.assertNotIn("analogRead", source)
        self.assertNotIn("Serial.", source)

    def test_single_c_submission_is_normalized_into_espidf_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("button_status_display", platform="esp32s3_espidf")
            paths = generate_case(task, root=root)
            submitted = root / "answer.c"
            submitted.write_text("void app_main(void) {}\n", encoding="utf-8")

            normalized = normalize_sketch_override(task, paths, submitted)

            assert normalized is not None
            self.assertTrue((normalized / "CMakeLists.txt").exists())
            self.assertTrue((normalized / "main" / "CMakeLists.txt").exists())
            self.assertEqual((normalized / "main" / "main.c").read_text(encoding="utf-8"), "void app_main(void) {}\n")

    def test_batch_submission_path_prefers_espidf_project_then_c_file(self):
        args = parse_args([
            "evaluate",
            "--platform",
            "esp32s3_espidf",
            "--task",
            "blink_led_1hz",
            "--sketch-dir",
            "submissions",
            "--output",
            "results.jsonl",
        ])
        task = load_task("blink_led_1hz", platform="esp32s3_espidf")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sketch_dir = root / args.sketch_dir
            sketch_dir.mkdir()
            self.assertEqual(submission_path_for_task(task, sketch_dir), sketch_dir / "blink_led_1hz.c")
            (sketch_dir / "blink_led_1hz").mkdir()
            self.assertEqual(submission_path_for_task(task, sketch_dir), sketch_dir / "blink_led_1hz")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
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

ESP32S3_LEVEL2_TASKS = {
    "rotary_encoder",
    "16key_keypad",
    "lcd1602_display_hello_world",
    "dht11_read",
    "ds1307_rtc",
    "mpu6050_read_i2c",
    "mpu6050_read_spi",
    "bme280_read_i2c",
    "bme280_read_spi",
    "tilt_detection_alarm",
    "photoresistor_nightlight",
    "ds18b20_heat_alarm",
    "clap_switch",
    "hcsr501_motion_alarm",
    "hcsr04_find_distance",
    "parking_sensor",
    "reverse_parking_sensor",
}

ESP32S3_LEVEL3_TASKS = {
    "dht11_read_button_display",
    "mpu6050_read_button_display",
    "mpu6050_read_periodic_display",
    "safebox",
    "safebox_display",
    "lcd1602_auto_brightness_control",
    "buzzer_toggle_led_freq",
    "tmp36_read_button_display",
    "tmp36_read_periodic_display",
    "reaction_timer_display",
    "sensor_water_level_display",
    "buzzer_laser_tripwire",
    "joystick_buzzer_pitch",
    "step_counter_print",
}

ESP32S3_FORBIDDEN_ARDUINO_CALLS = {
    "pinMode",
    "digitalRead",
    "digitalWrite",
    "analogRead",
    "delay",
    "tone",
    "Serial.begin",
    "Serial.print",
    "Serial.println",
    "Wire.begin",
    "SPI.begin",
    "LiquidCrystal",
    "Keypad",
}


class Esp32S3EspIdfProfileTests(unittest.TestCase):
    def test_profile_uses_espidf_board_and_firmware_contract(self):
        profile = board_profile_for_platform("esp32s3_espidf")

        self.assertEqual(profile.board_type, "board-esp32-s3-devkitc-1")
        self.assertEqual(profile.part_id, "esp")
        self.assertEqual(profile.build_kind, "espidf")
        self.assertEqual(profile.idf_target, "esp32s3")
        self.assertEqual(profile.firmware_kind, "espidf_flasher_args")
        self.assertEqual(profile.serial_interface, "USB_SERIAL_JTAG")
        self.assertEqual(profile.voltage, 3.3)
        self.assertEqual(profile.adc_max, 4095)
        self.assertEqual(profile.power_pin, "3V3.1")
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

    def test_all_upstream_level2_and_level3_tasks_load_and_have_prompts(self):
        expected = {
            "level2": ESP32S3_LEVEL2_TASKS,
            "level3": ESP32S3_LEVEL3_TASKS,
        }
        for level, task_ids in expected.items():
            tasks = list(iter_tasks(platform="esp32s3_espidf", level=level))
            self.assertEqual({task.task_id for task in tasks}, task_ids)
            for task in tasks:
                with self.subTest(level=level, task=task.task_id):
                    self.assertTrue(task.prompt_path.exists())
                    self.assertTrue(task.prompt_text.strip())
                    self.assertTrue(task.prompt_text.endswith("\n"))

    def test_generated_cases_use_espidf_layout_and_esp32s3_diagrams(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for level in ("level1", "level2", "level3"):
                for task in iter_tasks(platform="esp32s3_espidf", level=level):
                    with self.subTest(level=level, task=task.task_id):
                        if not task.is_supported:
                            continue
                        paths = generate_case(task, root=root)
                        diagram = paths.diagram.read_text(encoding="utf-8")
                        wokwi = paths.wokwi_toml.read_text(encoding="utf-8")

                        self.assertTrue((paths.sketch / "CMakeLists.txt").exists())
                        self.assertTrue((paths.sketch / "main" / "CMakeLists.txt").exists())
                        self.assertTrue((paths.sketch / "main" / "main.c").exists())
                        self.assertTrue((paths.sketch / "sdkconfig.defaults").exists())
                        sdkconfig = (paths.sketch / "sdkconfig.defaults").read_text(encoding="utf-8")
                        self.assertFalse(list(paths.sketch.rglob("*.ino")))
                        self.assertIn("board-esp32-s3-devkitc-1", diagram)
                        self.assertIn('"id": "esp"', diagram)
                        self.assertIn("esp:", diagram)
                        self.assertNotIn("mega:", diagram)
                        board = next(
                            part for part in json.loads(diagram)["parts"] if part.get("id") == "esp"
                        )
                        self.assertEqual(board["attrs"]["serialInterface"], "USB_SERIAL_JTAG")
                        self.assertIn("CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y", sdkconfig)
                        self.assertIn("# CONFIG_ESP_CONSOLE_UART_DEFAULT is not set", sdkconfig)
                        self.assertIn("CONFIG_BOOTLOADER_LOG_LEVEL_NONE=y", sdkconfig)
                        self.assertIn("CONFIG_LOG_DEFAULT_LEVEL_NONE=y", sdkconfig)
                        self.assertIn("firmware = 'artifacts/build/flasher_args.json'", wokwi)
                        self.assertIn(f"elf = 'artifacts/build/{task.sketch_name}.elf'", wokwi)

    def test_level2_and_level3_static_checks_reject_arduino_apis(self):
        for level in ("level2", "level3"):
            for task in iter_tasks(platform="esp32s3_espidf", level=level):
                with self.subTest(level=level, task=task.task_id):
                    if not task.is_supported:
                        continue
                    checks = task.validator.get("checks", [])
                    static_params = [
                        check.get("params", {})
                        for check in checks
                        if check.get("family") == "static_checks"
                    ]
                    self.assertTrue(static_params)
                    forbidden = set(static_params[0].get("forbidden_calls", []))
                    self.assertTrue(ESP32S3_FORBIDDEN_ARDUINO_CALLS.issubset(forbidden))
                    self.assertTrue(static_params[0].get("required_patterns"))

    def test_level2_and_level3_reference_source_is_espidf_not_arduino(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for level in ("level2", "level3"):
                for task in iter_tasks(platform="esp32s3_espidf", level=level):
                    with self.subTest(level=level, task=task.task_id):
                        if not task.is_supported:
                            continue
                        paths = generate_case(task, root=root)
                        source = (paths.sketch / "main" / "main.c").read_text(encoding="utf-8")

                        self.assertIn("void app_main(void)", source)
                        for arduino_api in ("pinMode", "digitalRead", "digitalWrite", "analogRead", "Serial."):
                            self.assertNotIn(arduino_api, source)

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

    def test_led_timing_tasks_ignore_esp32_startup_transients(self):
        expectations = {
            "blink_led_1hz": ["D0"],
            "blink_led_no_delay": ["D0"],
            "blink_two_leds": ["D0", "D1"],
        }
        for task_id, channels in expectations.items():
            with self.subTest(task=task_id):
                task = load_task(task_id, platform="esp32s3_espidf", level="level1")
                validator_channels = task.validator_params()["channels"]

                for channel in channels:
                    self.assertEqual(validator_channels[channel]["skip_startup_segments"], 2)

    def test_bme280_tasks_use_distinct_deterministic_variants(self):
        for task_id in ("bme280_read_i2c", "bme280_read_spi"):
            with self.subTest(task=task_id):
                task = load_task(task_id, platform="esp32s3_espidf", level="level2")

                self.assertEqual([variant["id"] for variant in task.simulation_variants], ["scenario_a", "scenario_b"])
                self.assertTrue(task.simulation.get("require_distinct_variant_outputs"))
                scenario_b = task.simulation_variants[1]
                self.assertEqual(scenario_b["attrs"]["bme1"]["temperatureC"], "31.0")
                self.assertEqual(
                    scenario_b["validator"]["checks"][1]["params"]["expected_pressure_pa"],
                    99000,
                )

    def test_mpu6050_spi_uses_deterministic_mpu_custom_chip(self):
        task = load_task("mpu6050_read_spi", platform="esp32s3_espidf", level="level2")

        self.assertTrue(task.is_supported)
        self.assertEqual(task.custom_chips, [{"name": "mpu6050", "binary": "chips/mpu6050.chip.wasm"}])
        self.assertEqual(task.fixture["components"][0]["type"], "mpu6050_spi")
        self.assertNotIn("bme280", task.path.read_text(encoding="utf-8").lower())
        self.assertEqual([variant["id"] for variant in task.simulation_variants], ["half_g", "one_and_half_g"])
        self.assertTrue(task.simulation.get("require_distinct_variant_outputs"))

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

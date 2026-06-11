import json
import tempfile
import unittest
from pathlib import Path

from bench.config import ConfigError, TaskConfig, board_profile_for_platform, load_task_file
from bench.diagrams import generate_diagram, validate_diagram_file
from bench.runner import generate_case, expected_firmware_paths
from bench.validators import position_to_tmp36_celsius


def esp32_task(case_dir: Path, *, family: str = "single_led_output") -> TaskConfig:
    fixture = {
        "family": family,
        "pins": {"led": "2"} if family == "single_led_output" else {"button": "4"},
    }
    if family == "single_led_output":
        fixture["analyzer"] = {"channels": [{"signal": "D0", "pin": "2"}]}
        validator = {
            "family": "waveform_frequency",
            "params": {
                "channels": {
                    "D0": {
                        "half_period_range_s": [0.45, 0.55],
                        "full_period_range_s": [0.9, 1.1],
                    }
                }
            },
        }
    else:
        validator = {"family": "serial_count_sequence", "params": {"expected_count": 1}}
    return TaskConfig(
        path=case_dir / "task.yaml",
        data={
            "task_id": f"esp32_{family}",
            "name": "ESP32 profile smoke task",
            "platform": "esp32",
            "fixture": fixture,
            "validator": validator,
            "case": {"id": f"esp32-{family}", "sketch_name": f"esp32_{family}"},
        },
    )


class BoardProfileTests(unittest.TestCase):
    def test_esp32_profile_defaults_board_and_firmware_contract(self):
        profile = board_profile_for_platform("esp32")
        self.assertEqual(profile.board_type, "board-esp32-devkit-c-v4")
        self.assertEqual(profile.part_id, "esp")
        self.assertEqual(profile.fqbn, "esp32:esp32:esp32")
        self.assertEqual(profile.firmware_extension, ".bin")
        self.assertEqual(profile.voltage, 3.3)
        self.assertEqual(profile.adc_max, 4095)

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(ConfigError):
            board_profile_for_platform("zephyr")

    def test_esp32_task_board_defaults_come_from_profile(self):
        task = esp32_task(Path("case"))

        self.assertEqual(task.board["type"], "board-esp32-devkit-c-v4")
        self.assertEqual(task.board["fqbn"], "esp32:esp32:esp32")


class Esp32DiagramTests(unittest.TestCase):
    def test_generated_esp32_diagram_rewrites_board_and_power_endpoints(self):
        task = esp32_task(Path("case"), family="button_serial")
        diagram = generate_diagram(task)
        endpoints = [
            endpoint
            for item in diagram["connections"]
            for endpoint in item[:2]
            if isinstance(endpoint, str)
        ]

        self.assertIn({"type": "board-esp32-devkit-c-v4", "id": "esp", "top": 120, "left": 20, "attrs": {}}, diagram["parts"])
        self.assertTrue(any(endpoint == "esp:3V3" for endpoint in endpoints))
        self.assertTrue(any(endpoint == "esp:GND.1" for endpoint in endpoints))
        self.assertFalse(any(endpoint.startswith("mega:") for endpoint in endpoints))

    def test_generated_esp32_diagram_lints(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task = esp32_task(case_dir)
            diagram = generate_diagram(task)
            path = case_dir / "diagram.json"
            path.write_text(json.dumps(diagram), encoding="utf-8")

            validate_diagram_file(path, task)


class Esp32RunnerTests(unittest.TestCase):
    def test_esp32_case_uses_bin_firmware_and_esp32_fqbn(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = esp32_task(Path(tmp))
            paths = generate_case(task, root=Path(tmp))
            firmware, elf = expected_firmware_paths(paths)
            text = paths.wokwi_toml.read_text(encoding="utf-8")
            sketch_yaml = (paths.sketch / "sketch.yaml").read_text(encoding="utf-8")

        self.assertEqual(firmware.name, f"{task.sketch_name}.ino.bin")
        self.assertEqual(elf.name, f"{task.sketch_name}.ino.elf")
        self.assertIn(f"artifacts/build/{task.sketch_name}.ino.bin", text)
        self.assertIn("default_fqbn: esp32:esp32:esp32", sketch_yaml)


class Tmp36ProfileTests(unittest.TestCase):
    def test_tmp36_position_helper_defaults_to_mega_voltage(self):
        self.assertEqual(position_to_tmp36_celsius(0.15), 25.0)

    def test_tmp36_position_helper_accepts_esp32_voltage(self):
        self.assertAlmostEqual(position_to_tmp36_celsius(0.15, voltage=3.3), -0.5)

    def test_config_lint_uses_platform_voltage_for_tmp36_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "esp32-tmp36.yaml"
            path.write_text(
                (
                    "task_id: esp32_tmp36\n"
                    "platform: esp32\n"
                    "support: {status: manual, reason: synthetic config lint fixture}\n"
                    "fixture:\n"
                    "  family: analog_temperature_serial\n"
                    "validator:\n"
                    "  family: analog_temperature_serial\n"
                    "  params:\n"
                    "    expected_celsius: [-17.0, -0.5]\n"
                    "    tolerance_celsius: 1.0\n"
                    "scenario:\n"
                    "  family: analog_position_sequence\n"
                    "  part_id: pot1\n"
                    "  positions:\n"
                    "    - value: 0.10\n"
                    "      duration_ms: 350\n"
                    "    - value: 0.15\n"
                    "      duration_ms: 350\n"
                    "case:\n"
                    "  id: esp32-tmp36\n"
                    "  sketch_name: esp32_tmp36\n"
                ),
                encoding="utf-8",
            )

            task = load_task_file(path)

        self.assertEqual(task.platform, "esp32")


if __name__ == "__main__":
    unittest.main()

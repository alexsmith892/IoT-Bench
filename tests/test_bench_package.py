import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.config import ConfigError, iter_tasks, load_task, load_task_file
from bench.diagrams import generate_diagram, validate_analyzer_wiring
from bench.results import COMPILE_FAIL, FAIL, PASS, SIM_INFRA_FAIL, SIM_OUTPUT_FAIL, SOURCE_USER_CODE, result_payload
from bench.runner import (
    BuildSimulationError,
    CasePaths,
    build_case,
    case_dir_for_task,
    expected_firmware_paths,
    generate_case,
    normalize_sketch_override,
    write_verification,
)
from bench.scenarios import generate_scenario
from bench.serial import extract_floats, extract_ints, monotonic_counter_reaches
from bench.static import StaticCheckError, validate_forbidden_calls
from bench.validators import validate_task


class BenchPackageTests(unittest.TestCase):
    def test_all_level1_task_configs_load(self):
        tasks = list(iter_tasks(platform="arduino_mega", level="level1"))

        self.assertEqual(len(tasks), 11)
        self.assertIn("blink_led_1hz", {task.task_id for task in tasks})
        self.assertIn("tmp36_read", {task.task_id for task in tasks})

    def test_bad_task_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text("task_id: bad\n", encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_task_file(path)

    def test_bad_family_specific_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text(
                (
                    "task_id: bad\n"
                    "fixture:\n"
                    "  family: single_led_output\n"
                    "validator:\n"
                    "  family: waveform_frequency\n"
                    "  params: {}\n"
                    "case:\n"
                    "  id: bad-case\n"
                    "  sketch_name: bad\n"
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_task_file(path)

    def test_dual_led_diagram_has_expected_analyzer_channels(self):
        task = load_task("blink_two_leds")
        diagram = generate_diagram(task)

        part_ids = {part["id"] for part in diagram["parts"]}
        self.assertIn("led1", part_ids)
        self.assertIn("led2", part_ids)
        validate_analyzer_wiring(diagram, task)

    def test_debounce_scenario_contains_synthetic_bounce(self):
        task = load_task("button_press_debounce")
        scenario = generate_scenario(task)

        assert scenario is not None
        pressed_values = [
            step["set-control"]["value"]
            for step in scenario["steps"]
            if "set-control" in step
        ]
        self.assertGreaterEqual(pressed_values.count(1), 3)
        self.assertGreaterEqual(pressed_values.count(0), 3)

    def test_static_check_ignores_comments_and_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch_dir = Path(tmp) / "sketch"
            sketch_dir.mkdir()
            sketch = sketch_dir / "sketch.ino"
            sketch.write_text(
                'void loop(){ Serial.println("delay(500)"); /* delay(1); */ }\n',
                encoding="utf-8",
            )

            validate_forbidden_calls(sketch_dir, ["delay", "delayMicroseconds"])

            sketch.write_text("void loop(){ delayMicroseconds(10); }\n", encoding="utf-8")
            with self.assertRaises(StaticCheckError):
                validate_forbidden_calls(sketch_dir, ["delay", "delayMicroseconds"])

    def test_serial_helpers_extract_counts_and_temperatures(self):
        text = "count: 1\ncount: 2\ncount: 3\ntemp: 24.8\n"

        self.assertTrue(monotonic_counter_reaches(extract_ints(text), 3))
        self.assertTrue(any(abs(value - 24.8) < 0.001 for value in extract_floats(text)))

    def test_multi_channel_frequency_validator_accepts_synthetic_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("blink_two_leds")
            case_dir = root / "case"
            sketch_dir = case_dir / "sketch" / "blink_two_leds"
            sketch_dir.mkdir(parents=True)
            (sketch_dir / "blink_two_leds.ino").write_text(
                "void setup(){}\nvoid loop(){ millis(); }\n",
                encoding="utf-8",
            )
            vcd = case_dir / "artifacts" / "logic" / "wokwi.vcd"
            write_two_channel_vcd(vcd, d0_half_s=0.5, d1_half_s=0.25, cycles=6)

            result = validate_task(
                task,
                CasePaths(
                    task_id=task.task_id,
                    case_id="case",
                    case_dir=case_dir,
                    sketch=sketch_dir,
                    diagram=case_dir / "diagram.json",
                    wokwi_toml=case_dir / "wokwi.toml",
                    build_dir=case_dir / "artifacts" / "build",
                    fqbn="arduino:avr:mega",
                    vcd=vcd,
                ),
            )

            self.assertEqual(result.classification, "PASS", result.payload())

    def test_serial_count_validator_accepts_monotonic_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("button_status_count")
            serial_log = root / "serial.log"
            serial_log.write_text("Count: 1\nCount: 2\nCount: 3\n", encoding="utf-8")

            result = validate_task(
                task,
                CasePaths(
                    task_id=task.task_id,
                    case_id="case",
                    case_dir=root,
                    sketch=root / "sketch",
                    diagram=root / "diagram.json",
                    wokwi_toml=root / "wokwi.toml",
                    build_dir=root / "build",
                    fqbn="arduino:avr:mega",
                    serial_log=serial_log,
                ),
            )

            self.assertEqual(result.classification, "PASS", result.payload())

    def test_generated_case_dirs_match_task_configs(self):
        for task in iter_tasks(platform="arduino_mega", level="level1"):
            self.assertTrue(case_dir_for_task(task).exists(), task.task_id)

    def test_generate_case_creates_complete_wokwi_project_structure(self):
        expected_dirs = [
            "artifacts/build",
            "artifacts/logic",
            "artifacts/serial",
            "artifacts/archive/vcd",
            "artifacts/archive/serial",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for task in iter_tasks(platform="arduino_mega", level="level1"):
                paths = generate_case(task, root=root)
                self.assertTrue((paths.case_dir / "case.yaml").exists(), task.task_id)
                self.assertTrue((paths.case_dir / "case.json").exists(), task.task_id)
                self.assertTrue(paths.diagram.exists(), task.task_id)
                self.assertTrue(paths.wokwi_toml.exists(), task.task_id)
                self.assertTrue((paths.sketch / f"{task.sketch_name}.ino").exists(), task.task_id)
                self.assertTrue((paths.sketch / "sketch.yaml").exists(), task.task_id)
                for directory in expected_dirs:
                    self.assertTrue((paths.case_dir / directory).is_dir(), f"{task.task_id}: {directory}")
                if task.scenario:
                    self.assertTrue(paths.scenario and paths.scenario.exists(), task.task_id)

    def test_result_payload_maps_internal_classes_to_benchmark_result(self):
        self.assertEqual(result_payload(PASS, "ok")["result"], "BC")
        self.assertEqual(result_payload(FAIL, "bad")["result"], "BF")
        self.assertEqual(result_payload(COMPILE_FAIL, "compile")["result"], "CF")
        self.assertEqual(result_payload(SIM_INFRA_FAIL, "infra")["result"], "IF")
        self.assertEqual(result_payload(SIM_OUTPUT_FAIL, "artifact")["result"], "IF")
        self.assertIsNone(result_payload(PASS, "ok")["failure_source"])
        self.assertEqual(result_payload(FAIL, "bad")["failure_source"], SOURCE_USER_CODE)

    def test_build_case_fails_if_expected_firmware_is_missing_after_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task("blink_led_1hz")
            paths = generate_case(task, root=Path(tmp))

            with patch("bench.runner.run_checked", return_value=None):
                with self.assertRaises(BuildSimulationError) as caught:
                    build_case(task, paths, arduino_cli="arduino-cli")

            # Compile succeeded (run_checked patched to no-op) but no binary was
            # produced: this is an artifact/toolchain failure (-> IF), not a model
            # compile failure (CF).
            self.assertEqual(caught.exception.classification, "SIM_OUTPUT_FAIL")
            self.assertEqual(caught.exception.failure_stage, "sim_output")

    def test_expected_firmware_paths_match_wokwi_toml_contract(self):
        task = load_task("tmp36_read")
        paths = generate_case(task)
        firmware_hex, firmware_elf = expected_firmware_paths(paths)
        text = paths.wokwi_toml.read_text(encoding="utf-8")

        self.assertIn(f"artifacts/build/{task.sketch_name}.ino.hex", text)
        self.assertIn(f"artifacts/build/{task.sketch_name}.ino.elf", text)
        self.assertEqual(firmware_hex, paths.case_dir / "artifacts" / "build" / f"{task.sketch_name}.ino.hex")
        self.assertEqual(firmware_elf, paths.case_dir / "artifacts" / "build" / f"{task.sketch_name}.ino.elf")

    def test_verification_manifest_uses_portable_case_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task("tmp36_read")
            paths = generate_case(task, root=Path(tmp))
            paths.firmware_hex.write_text("hex\n", encoding="utf-8")
            paths.firmware_elf.write_text("elf\n", encoding="utf-8")
            assert paths.serial_log is not None
            paths.serial_log.write_text("temp: 25.0\n", encoding="utf-8")

            manifest_path = write_verification(
                task,
                paths,
                result_payload(PASS, "ok"),
                command="test",
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["sketch_path"], f"sketch/{task.sketch_name}")
            self.assertEqual(manifest["diagram_path"], "diagram.json")
            self.assertEqual(manifest["firmware_hex"], f"artifacts/build/{task.sketch_name}.ino.hex")
            self.assertEqual(manifest["firmware_elf"], f"artifacts/build/{task.sketch_name}.ino.elf")
            self.assertEqual(manifest["serial_log_path"], "artifacts/serial/serial.log")
            self.assertIsNone(manifest["failure_source"])

    def test_invalid_scenario_values_and_durations_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-pir.yaml"
            path.write_text(
                (
                    "task_id: bad_pir\n"
                    "fixture:\n"
                    "  family: pir_serial\n"
                    "validator:\n"
                    "  family: serial_contains_on_stimulus\n"
                    "  params:\n"
                    "    expected_texts: ['Motion Detected!', 'No Motion Detected!']\n"
                    "    state_texts: {'0': 'No Motion Detected!', '1': 'Motion Detected!'}\n"
                    "scenario:\n"
                    "  family: pir_state_sequence\n"
                    "  part_id: pir1\n"
                    "  states:\n"
                    "    - value: 2\n"
                    "      duration_ms: 100\n"
                    "case:\n"
                    "  id: bad-pir\n"
                    "  sketch_name: bad_pir\n"
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_task_file(path)

            path.write_text(
                path.read_text(encoding="utf-8").replace("value: 2", "value: 1").replace(
                    "duration_ms: 100", "duration_ms: 0"
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_task_file(path)

    def test_tmp36_expected_temperatures_must_match_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-tmp36.yaml"
            path.write_text(
                (
                    "task_id: bad_tmp36\n"
                    "fixture:\n"
                    "  family: analog_temperature_serial\n"
                    "validator:\n"
                    "  family: analog_temperature_serial\n"
                    "  params:\n"
                    "    expected_celsius: [25.0, 0.0]\n"
                    "    tolerance_celsius: 6.0\n"
                    "scenario:\n"
                    "  family: analog_position_sequence\n"
                    "  part_id: pot1\n"
                    "  positions:\n"
                    "    - value: 0.10\n"
                    "      duration_ms: 350\n"
                    "    - value: 0.15\n"
                    "      duration_ms: 350\n"
                    "case:\n"
                    "  id: bad-tmp36\n"
                    "  sketch_name: bad_tmp36\n"
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_task_file(path)

    def test_sketch_override_file_is_normalized_to_task_sketch_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task("button_status_display")
            paths = generate_case(task, root=Path(tmp))
            submitted = Path(tmp) / "answer.ino"
            submitted.write_text("void setup(){}\nvoid loop(){}\n", encoding="utf-8")

            normalized = normalize_sketch_override(task, paths, submitted)

            assert normalized is not None
            self.assertEqual(normalized.name, task.sketch_name)
            self.assertTrue((normalized / f"{task.sketch_name}.ino").exists())

    def test_ambiguous_multi_ino_sketch_override_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task("button_status_display")
            paths = generate_case(task, root=Path(tmp))
            submitted = Path(tmp) / "submission"
            submitted.mkdir()
            (submitted / "a.ino").write_text("void setup(){}\n", encoding="utf-8")
            (submitted / "b.ino").write_text("void loop(){}\n", encoding="utf-8")

            with self.assertRaises(BuildSimulationError) as caught:
                normalize_sketch_override(task, paths, submitted)

            self.assertEqual(caught.exception.classification, "COMPILE_FAIL")
            self.assertEqual(caught.exception.failure_source, SOURCE_USER_CODE)


def write_two_channel_vcd(path: Path, *, d0_half_s: float, d1_half_s: float, cycles: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events: dict[float, list[str]] = {}

    def add(time_s: float, value: int, symbol: str) -> None:
        events.setdefault(round(time_s, 9), []).append(f"{value}{symbol}")

    add(0.0, 0, "!")
    add(0.0, 0, "?")
    for half_s, symbol in ((d0_half_s, "!"), (d1_half_s, "?")):
        timestamp = 0.1
        value = 1
        add(timestamp, value, symbol)
        for _ in range(cycles * 2):
            timestamp += half_s
            value = 1 - value
            add(timestamp, value, symbol)

    lines = [
        "$version synthetic bench test $end",
        "$timescale 1ns $end",
        "$scope module logic $end",
        "$var wire 1 ! D0 $end",
        "$var wire 1 ? D1 $end",
        "$upscope $end",
        "$enddefinitions $end",
    ]
    for timestamp in sorted(events):
        lines.append(f"#{round(timestamp * 1_000_000_000)}")
        lines.extend(events[timestamp])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

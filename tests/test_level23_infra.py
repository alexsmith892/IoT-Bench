import tempfile
import unittest
from pathlib import Path

from bench.cli import build_single_task, run_single_task
from bench.config import iter_tasks, load_task, TaskConfig
from bench.diagrams import DiagramError, generate_diagram, validate_analyzer_wiring, validate_diagram_file
from bench.lcd1602 import decode_lcd1602_vcd
from bench.runner import CaseConfigError, CasePaths, case_dir_for_task, generate_case
from bench.scenarios import generate_scenario
from bench.static import StaticCheckError, validate_static_checks
from bench.validators import validate_task


class Level23InfrastructureTests(unittest.TestCase):
    def test_level2_and_level3_task_configs_load(self):
        self.assertEqual(len(list(iter_tasks(platform="arduino_mega", level="level2"))), 16)
        self.assertEqual(len(list(iter_tasks(platform="arduino_mega", level="level3"))), 14)

    def test_generated_case_dirs_exist_for_level2_and_level3(self):
        for level in ("level2", "level3"):
            for task in iter_tasks(platform="arduino_mega", level=level):
                self.assertTrue(case_dir_for_task(task).exists(), task.task_id)

    def test_composite_lcd_diagram_wires_analyzer_channels(self):
        task = load_task("lcd1602_display_hello_world", level="level2")
        diagram = generate_diagram(task)
        part_ids = {part["id"] for part in diagram["parts"]}

        self.assertIn("lcd1", part_ids)
        self.assertIn("logic1", part_ids)
        validate_analyzer_wiring(diagram, task)

    def test_timeline_scenario_generates_controls_and_delays(self):
        task = load_task("clap_switch", level="level2")
        scenario = generate_scenario(task)

        assert scenario is not None
        controls = [step["set-control"] for step in scenario["steps"] if "set-control" in step]
        self.assertEqual([item["value"] for item in controls], [1, 0, 1, 0])
        self.assertEqual({item["part-id"] for item in controls}, {"sound1"})

    def test_static_checks_support_required_patterns_and_any_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch_dir = Path(tmp)
            (sketch_dir / "sketch.ino").write_text(
                'void setup(){ pinMode(2, INPUT); Serial.println("Wire.begin()"); }\n'
                "void loop(){ digitalRead(2); }\n",
                encoding="utf-8",
            )

            validate_static_checks(
                sketch_dir,
                {
                    "required_patterns": [r"pinMode\s*\(\s*2", r"digitalRead\s*\(\s*2"],
                    "required_any_patterns": [[r"attachInterrupt", r"digitalRead\s*\(\s*2"]],
                },
            )

            with self.assertRaises(StaticCheckError):
                validate_static_checks(sketch_dir, {"required_patterns": [r"Wire\.begin\s*\("]})

    def test_lcd_decoder_reconstructs_4bit_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            vcd = Path(tmp) / "lcd.vcd"
            write_lcd_vcd(vcd, "Hello World")

            frame = decode_lcd1602_vcd(
                vcd,
                signals={
                    "rs": "LCD_RS",
                    "e": "LCD_E",
                    "d4": "LCD_D4",
                    "d5": "LCD_D5",
                    "d6": "LCD_D6",
                    "d7": "LCD_D7",
                },
            )

            self.assertIn("Hello World", frame.text())

    def test_composite_serial_validator_accepts_ordered_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("dht11_read", level="level2")
            sketch = root / "sketch"
            sketch.mkdir()
            (sketch / "dht11_read.ino").write_text(
                "void setup(){ pinMode(14, INPUT); }\nvoid loop(){}\n",
                encoding="utf-8",
            )
            serial_log = root / "serial.log"
            serial_log.write_text(
                "Temperature: 18.0 C Humidity: 35.0 %\nTemperature: 31.0 C Humidity: 65.0 %\n",
                encoding="utf-8",
            )

            result = validate_task(task, case_paths(task, root, sketch=sketch, serial_log=serial_log))

            self.assertEqual(result.classification, "PASS", result.payload())

    def test_window_ratio_validator_rejects_wrong_output_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("photoresistor_nightlight", level="level2")
            vcd = root / "wrong.vcd"
            write_digital_vcd(vcd, "D0", [(0.0, 0), (1.1, 0)])

            result = validate_task(task, case_paths(task, root, vcd=vcd))

            self.assertEqual(result.classification, "FAIL", result.payload())

    def test_generate_case_creates_level2_and_level3_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for task in (
                load_task("lcd1602_display_hello_world", level="level2"),
                load_task("sensor_water_level_display", level="level3"),
            ):
                paths = generate_case(task, root=root)
                self.assertTrue(paths.diagram.exists())
                self.assertTrue((paths.sketch / f"{task.sketch_name}.ino").exists())
                self.assertTrue((paths.case_dir / "case.yaml").exists())

    def test_bme_i2c_task_generates_with_declared_custom_chip(self):
        task = load_task("bme280_read_i2c", level="level2")

        with tempfile.TemporaryDirectory() as tmp:
            paths = generate_case(task, root=Path(tmp))
            self.assertTrue((paths.case_dir / "chips" / "bme280.chip.wasm").exists())
            self.assertTrue((paths.case_dir / "chips" / "bme280.chip.json").exists())
            self.assertIn("[[chip]]", paths.wokwi_toml.read_text(encoding="utf-8"))

    def test_diagram_lint_rejects_unknown_parts_and_accepts_declared_custom_chips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("lcd1602_display_hello_world", level="level2")
            bad = root / "bad.json"
            bad.write_text(
                '{"version":1,"parts":[{"type":"wokwi-arduino-mega","id":"mega"},{"type":"board-bme280","id":"bme1"}],"connections":[]}',
                encoding="utf-8",
            )
            with self.assertRaises(DiagramError):
                validate_diagram_file(bad, task)

            custom_task = TaskConfig(
                path=root / "custom.yaml",
                data={
                    **task.data,
                    "fixture": {"family": "composite", "components": []},
                    "custom_chips": [{"name": "sensor", "binary": "chips/sensor.chip.wasm"}],
                },
            )
            chip_dir = root / "chips"
            chip_dir.mkdir()
            (chip_dir / "sensor.chip.wasm").write_bytes(b"wasm")
            (chip_dir / "sensor.chip.json").write_text("{}", encoding="utf-8")
            (root / "wokwi.toml").write_text(
                "[wokwi]\nversion = 1\n\n[[chip]]\nname = 'sensor'\nbinary = 'chips/sensor.chip.wasm'\n",
                encoding="utf-8",
            )
            good = root / "diagram.json"
            good.write_text(
                '{"version":1,"parts":[{"type":"wokwi-arduino-mega","id":"mega"},{"type":"chip-sensor","id":"sensor1"}],"connections":[]}',
                encoding="utf-8",
            )

            validate_diagram_file(good, custom_task)

    def test_control_sequence_scenario_generates_generic_controls(self):
        task = load_task("dht11_read", level="level2")
        scenario = generate_scenario(task)

        assert scenario is not None
        controls = [step["set-control"] for step in scenario["steps"] if "set-control" in step]
        self.assertEqual([item["part-id"] for item in controls], ["dht1", "dht1", "dht1", "dht1"])
        self.assertEqual([item["control"] for item in controls], ["temperature", "humidity", "temperature", "humidity"])

    def test_serial_observation_sequence_rejects_hardcoded_single_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("dht11_read", level="level2")
            sketch = root / "sketch"
            sketch.mkdir()
            (sketch / "dht11_read.ino").write_text(
                "void setup(){ pinMode(14, INPUT); }\nvoid loop(){}\n",
                encoding="utf-8",
            )
            serial_log = root / "serial.log"
            serial_log.write_text(
                "Temperature: 18.0 C Humidity: 35.0 %\nTemperature: 18.0 C Humidity: 35.0 %\n",
                encoding="utf-8",
            )

            result = validate_task(task, case_paths(task, root, sketch=sketch, serial_log=serial_log))

            self.assertEqual(result.classification, "FAIL", result.payload())

    def test_bus_activity_validator_rejects_missing_transitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = TaskConfig(
                path=root / "bus.yaml",
                data={
                    "task_id": "bus_test",
                    "fixture": {"family": "composite", "analyzer": {"channels": [{"signal": "D0", "pin": "20"}]}},
                    "validator": {"family": "bus_activity", "params": {"bus": "i2c", "pins": ["D0"], "min_transitions": 2}},
                    "case": {"id": "bus-test", "sketch_name": "bus_test"},
                },
            )
            vcd = root / "flat.vcd"
            write_digital_vcd(vcd, "D0", [(0.0, 1), (1.0, 1)])

            result = validate_task(task, case_paths(task, root, vcd=vcd))

            self.assertEqual(result.classification, "FAIL", result.payload())

    def test_stimulus_to_output_counts_output_held_high_until_trace_end(self):
        # Regression: an output driven HIGH that never transitions again has no
        # closing event; its final level must still be measured in a later window.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = TaskConfig(
                path=root / "s2o.yaml",
                data={
                    "task_id": "s2o_test",
                    "fixture": {"family": "composite", "analyzer": {"channels": [{"signal": "D0", "pin": "3"}]}},
                    "validator": {
                        "family": "stimulus_to_output",
                        "params": {
                            "channel": "D0",
                            "active_windows_s": [[0.70, 0.95]],
                            "inactive_windows_s": [[0.30, 0.55]],
                        },
                    },
                    "case": {"id": "s2o-test", "sketch_name": "s2o_test"},
                },
            )
            vcd = root / "held_high.vcd"
            write_digital_vcd(vcd, "D0", [(0.0, 0), (0.60, 1)])  # rises at 0.6, stays high

            result = validate_task(task, case_paths(task, root, vcd=vcd))

            self.assertEqual(result.classification, "PASS", result.payload())
            self.assertEqual(result.metrics["active_high_ratios"], [1.0])
            self.assertEqual(result.metrics["inactive_high_ratios"], [0.0])

    def test_buzzer_activity_distinguishes_beep_from_silence(self):
        def buzzer_task(root: Path) -> TaskConfig:
            return TaskConfig(
                path=root / "buzzer.yaml",
                data={
                    "task_id": "buzzer_test",
                    "fixture": {"family": "composite", "analyzer": {"channels": [{"signal": "D1", "pin": "3"}]}},
                    "validator": {"family": "bus_activity", "params": {"bus": "buzzer", "pins": ["D1"], "min_transitions": 8}},
                    "case": {"id": "buzzer-test", "sketch_name": "buzzer_test"},
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            beeping = root / "beep.vcd"
            tone = [(0.20 + i * 0.00025, i % 2) for i in range(1, 20)]
            write_digital_vcd(beeping, "D1", [(0.0, 0), *tone, (1.0, 0)])
            silent = root / "silent.vcd"
            write_digital_vcd(silent, "D1", [(0.0, 0), (1.0, 0)])

            self.assertEqual(
                validate_task(buzzer_task(root), case_paths(buzzer_task(root), root, vcd=beeping)).classification,
                "PASS",
            )
            self.assertEqual(
                validate_task(buzzer_task(root), case_paths(buzzer_task(root), root, vcd=silent)).classification,
                "FAIL",
            )

    def test_lcd_text_sequence_validator_observes_intermediate_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = TaskConfig(
                path=root / "lcd.yaml",
                data={
                    "task_id": "lcd_sequence",
                    "fixture": {"family": "composite", "analyzer": {"channels": [{"signal": "D0", "pin": "12"}]}},
                    "validator": {
                        "family": "lcd_text_sequence",
                        "params": {
                            "signals": {
                                "rs": "LCD_RS",
                                "e": "LCD_E",
                                "d4": "LCD_D4",
                                "d5": "LCD_D5",
                                "d6": "LCD_D6",
                                "d7": "LCD_D7",
                            },
                            "frames": [{"expected_texts": ["Hello"]}, {"expected_texts": ["Hello World"]}],
                        },
                    },
                    "case": {"id": "lcd-sequence", "sketch_name": "lcd_sequence"},
                },
            )
            vcd = root / "lcd.vcd"
            write_lcd_vcd(vcd, "Hello World")

            result = validate_task(task, case_paths(task, root, vcd=vcd))

            self.assertEqual(result.classification, "PASS", result.payload())


def case_paths(
    task,
    root: Path,
    *,
    sketch: Path | None = None,
    vcd: Path | None = None,
    serial_log: Path | None = None,
) -> CasePaths:
    return CasePaths(
        task_id=task.task_id,
        case_id="case",
        case_dir=root,
        sketch=sketch or root / "sketch",
        diagram=root / "diagram.json",
        wokwi_toml=root / "wokwi.toml",
        build_dir=root / "build",
        fqbn="arduino:avr:mega",
        vcd=vcd,
        serial_log=serial_log,
    )


def write_lcd_vcd(path: Path, text: str) -> None:
    events: dict[float, list[str]] = {}
    symbols = {"LCD_RS": "!", "LCD_E": '"', "LCD_D4": "#", "LCD_D5": "$", "LCD_D6": "%", "LCD_D7": "&"}
    current = {name: 0 for name in symbols}

    def set_signal(time_s: float, name: str, value: int) -> None:
        if current[name] == value:
            return
        current[name] = value
        events.setdefault(round(time_s, 9), []).append(f"{value}{symbols[name]}")

    def write_nibble(time_s: float, rs: int, nibble: int) -> float:
        set_signal(time_s, "LCD_RS", rs)
        for bit, name in enumerate(("LCD_D4", "LCD_D5", "LCD_D6", "LCD_D7")):
            set_signal(time_s, name, (nibble >> bit) & 1)
        set_signal(time_s + 0.000001, "LCD_E", 1)
        set_signal(time_s + 0.000002, "LCD_E", 0)
        return time_s + 0.000050

    def write_byte(time_s: float, rs: int, byte: int) -> float:
        time_s = write_nibble(time_s, rs, byte >> 4)
        return write_nibble(time_s, rs, byte & 0x0F)

    t = 0.0001
    t = write_byte(t, 0, 0x80)
    for char in text:
        t = write_byte(t, 1, ord(char))

    lines = [
        "$version synthetic lcd test $end",
        "$timescale 1ns $end",
        "$scope module logic $end",
    ]
    lines.extend(f"$var wire 1 {symbol} {name} $end" for name, symbol in symbols.items())
    lines.extend(["$upscope $end", "$enddefinitions $end", "#0"])
    lines.extend(f"0{symbol}" for symbol in symbols.values())
    for timestamp in sorted(events):
        lines.append(f"#{round(timestamp * 1_000_000_000)}")
        lines.extend(events[timestamp])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_digital_vcd(path: Path, signal: str, events: list[tuple[float, int]]) -> None:
    lines = [
        "$version synthetic digital test $end",
        "$timescale 1ns $end",
        "$scope module logic $end",
        f"$var wire 1 ! {signal} $end",
        "$upscope $end",
        "$enddefinitions $end",
    ]
    for timestamp_s, value in events:
        lines.append(f"#{round(timestamp_s * 1_000_000_000)}")
        lines.append(f"{value}!")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

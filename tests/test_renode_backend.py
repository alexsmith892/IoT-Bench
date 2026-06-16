"""Offline tests for the Renode/Zephyr backend seam (no Renode/west needed)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bench.config import BOARD_PROFILES, TaskConfig
from bench.renode import (
    RenodeConfigError,
    generate_repl,
    generate_resc,
    parse_gpio_pin,
    scenario_steps_to_resc,
)
from bench.runner import (
    case_paths_from_task,
    expected_firmware_paths,
    paths_for_variant,
)
from bench.scenarios import generate_scenario


def blink_task(case_dir_name: str = "blink-1hz-renode-nano33") -> TaskConfig:
    return TaskConfig(
        path=Path("tasks/zephyr_nano33ble/level1/blink_led_1hz.yaml"),
        data={
            "task_id": "blink_led_1hz",
            "platform": "zephyr_nano33ble",
            "level": "level1",
            "fixture": {
                "family": "single_led_output",
                "pins": {"led": "P0.24"},
                "analyzer": {"channels": [{"signal": "D0", "pin": "P0.24"}]},
            },
            "validator": {"family": "waveform_frequency", "params": {}},
            "simulation": {"timeout_ms": 6000},
            "case": {"id": case_dir_name, "sketch_name": "blink_1hz_renode_nano33"},
        },
    )


def button_task() -> TaskConfig:
    return TaskConfig(
        path=Path("tasks/zephyr_nano33ble/level1/button_status_count.yaml"),
        data={
            "task_id": "button_status_count",
            "platform": "zephyr_nano33ble",
            "level": "level1",
            "fixture": {"family": "button_serial", "pins": {"button": "P1.11"}},
            "validator": {"family": "serial_count_sequence", "params": {}},
            "scenario": {
                "family": "button_press_sequence",
                "part_id": "btn1",
                "initial_delay_ms": 200,
                "presses": [
                    {"duration_ms": 150, "after_ms": 250},
                    {"duration_ms": 150, "after_ms": 250},
                ],
            },
            "simulation": {"timeout_ms": 3000},
            "case": {"id": "button-status-count-renode-nano33", "sketch_name": "button_count"},
        },
    )


class BoardProfileTests(unittest.TestCase):
    def test_zephyr_profile_selects_renode_backend(self) -> None:
        profile = BOARD_PROFILES["zephyr_nano33ble"]
        self.assertEqual(profile.backend, "renode")
        self.assertEqual(profile.build_kind, "zephyr")
        self.assertEqual(profile.firmware_kind, "zephyr_image")
        self.assertEqual(profile.zephyr_board, "arduino_nano_33_ble")
        self.assertEqual(profile.voltage, 3.3)
        self.assertEqual(profile.adc_max, 4095)

    def test_wokwi_profiles_keep_wokwi_backend(self) -> None:
        for platform in ("arduino_mega", "esp32", "esp32s3_espidf"):
            self.assertEqual(BOARD_PROFILES[platform].backend, "wokwi")


class CasePathsTests(unittest.TestCase):
    def test_renode_case_paths(self) -> None:
        task = blink_task()
        paths = case_paths_from_task(task, Path("cases") / task.case_id)
        self.assertEqual(paths.diagram.name, "case.repl")
        self.assertIsNotNone(paths.resc)
        self.assertEqual(paths.resc.name, "case.resc")
        self.assertEqual(paths.vcd.name, "renode.vcd")

    def test_zephyr_firmware_paths(self) -> None:
        task = blink_task()
        paths = case_paths_from_task(task, Path("cases") / task.case_id)
        image, elf = expected_firmware_paths(paths)
        self.assertEqual(image, paths.build_dir / "zephyr" / "zephyr.hex")
        self.assertEqual(elf, paths.build_dir / "zephyr" / "zephyr.elf")

    def test_variant_paths_use_repl_and_resc(self) -> None:
        task = blink_task()
        paths = case_paths_from_task(task, Path("cases") / task.case_id)
        variant = paths_for_variant(paths, "v1", None)
        self.assertEqual(variant.diagram.name, "case.repl")
        self.assertIn("variants", str(variant.diagram))
        self.assertEqual(variant.resc.name, "case.resc")
        self.assertIn("variants", str(variant.resc))

    def test_wokwi_case_paths_unchanged(self) -> None:
        task = TaskConfig(
            path=Path("tasks/arduino_mega/level1/blink_led_1hz.yaml"),
            data={
                "task_id": "blink_led_1hz",
                "fixture": {
                    "family": "single_led_output",
                    "pins": {"led": "3"},
                    "analyzer": {"channels": [{"signal": "D0", "pin": "3"}]},
                },
                "validator": {"family": "waveform_frequency"},
                "case": {"id": "blink-1hz-wokwi-mega", "sketch_name": "blink_1hz_wokwi_mega"},
            },
        )
        paths = case_paths_from_task(task, Path("cases") / task.case_id)
        self.assertEqual(paths.diagram.name, "diagram.json")
        self.assertIsNone(paths.resc)
        self.assertEqual(paths.vcd.name, "wokwi.vcd")


class PinParsingTests(unittest.TestCase):
    def test_port_pin_specs(self) -> None:
        self.assertEqual(parse_gpio_pin("P0.24"), ("gpio0", 24))
        self.assertEqual(parse_gpio_pin("P1.11"), ("gpio1", 11))
        self.assertEqual(parse_gpio_pin("4"), ("gpio0", 4))

    def test_rejects_unknown_specs(self) -> None:
        for bad in ("P2.01", "A0", "D13", ""):
            with self.assertRaises(RenodeConfigError):
                parse_gpio_pin(bad)


class ReplGenerationTests(unittest.TestCase):
    def test_blink_repl_has_probe_and_uart_fix(self) -> None:
        repl = generate_repl(blink_task())
        self.assertIn('using "platforms/cpus/nrf52840.repl"', repl)
        self.assertIn("easyDMA: false", repl)
        self.assertIn("probe_d0: Miscellaneous.LED @ gpio0 24", repl)

    def test_button_repl_declares_button(self) -> None:
        repl = generate_repl(button_task())
        self.assertIn("btn1: Miscellaneous.Button @ gpio1 11", repl)
        self.assertIn("-> gpio1@11", repl)


class ScenarioToRescTests(unittest.TestCase):
    def test_button_press_sequence(self) -> None:
        task = button_task()
        commands, elapsed = scenario_steps_to_resc(task, generate_scenario(task))
        self.assertEqual(
            commands,
            [
                'emulation RunFor "0.200000"',
                "gpio1.btn1 Press",
                'emulation RunFor "0.150000"',
                "gpio1.btn1 Release",
                'emulation RunFor "0.250000"',
                "gpio1.btn1 Press",
                'emulation RunFor "0.150000"',
                "gpio1.btn1 Release",
                'emulation RunFor "0.250000"',
            ],
        )
        self.assertAlmostEqual(elapsed, 1.0)

    def test_unknown_part_rejected(self) -> None:
        task = button_task()
        scenario = {
            "steps": [
                {"set-control": {"part-id": "ghost", "control": "pressed", "value": 1}}
            ]
        }
        with self.assertRaises(RenodeConfigError):
            scenario_steps_to_resc(task, scenario)

    def test_unknown_control_rejected(self) -> None:
        task = button_task()
        scenario = {
            "steps": [
                {"set-control": {"part-id": "btn1", "control": "temperature", "value": 25}}
            ]
        }
        with self.assertRaises(RenodeConfigError):
            scenario_steps_to_resc(task, scenario)


class RescGenerationTests(unittest.TestCase):
    def test_blink_resc_shape(self) -> None:
        task = blink_task()
        resc = generate_resc(
            task,
            repl_relpath="case.repl",
            elf_relpath="artifacts/build/zephyr/zephyr.elf",
            serial_abspath=None,
            vcd_abspath=r"C:\abs path\renode.vcd",
            scenario=None,
            timeout_ms=6000,
        )
        self.assertIn("machine LoadPlatformDescription @case.repl", resc)
        self.assertIn("sysbus LoadELF @artifacts/build/zephyr/zephyr.elf", resc)
        self.assertIn("cpu VectorTableOffset 0x10000", resc)
        self.assertIn('emulation RunFor "6.000000"', resc)
        self.assertIn("iotbench_write_vcd()", resc)
        self.assertTrue(resc.rstrip().endswith("quit"))
        self.assertNotIn("CreateFileBackend", resc)

    def test_scenario_budget_enforced(self) -> None:
        task = button_task()
        with self.assertRaises(RenodeConfigError):
            generate_resc(
                task,
                repl_relpath="case.repl",
                elf_relpath="artifacts/build/zephyr/zephyr.elf",
                serial_abspath=r"C:\abs\serial.log",
                vcd_abspath=None,
                scenario=generate_scenario(task),
                timeout_ms=500,
            )


def imu_task() -> TaskConfig:
    return TaskConfig(
        path=Path("tasks/zephyr_nano33ble/level2/lsm9ds1_read_i2c.yaml"),
        data={
            "task_id": "lsm9ds1_read_i2c",
            "platform": "zephyr_nano33ble",
            "level": "level2",
            "fixture": {
                "family": "composite",
                "components": [
                    {"type": "lsm9ds1", "id": "imu1", "bus": "twi0", "address": "0x6b"}
                ],
            },
            "validator": {"family": "serial_observation_sequence", "params": {}},
            "simulation": {"timeout_ms": 1600},
            "case": {"id": "lsm9ds1-read-i2c-renode-nano33", "sketch_name": "lsm9ds1_read_i2c"},
        },
    )


class SensorPartTests(unittest.TestCase):
    def test_sensor_repl_declaration(self) -> None:
        repl = generate_repl(imu_task())
        self.assertIn("imu1: Sensors.LSM9DS1_IMU @ twi0 0x6b", repl)

    def test_sensor_control_commands(self) -> None:
        from bench.renode import control_set_command, renode_parts

        task = imu_task()
        parts = renode_parts(task)
        self.assertEqual(
            control_set_command(task, "imu1", parts["imu1"], "accelX", 0.5),
            "twi0.imu1 AccelerationX 0.5",
        )
        self.assertEqual(
            control_set_command(task, "imu1", parts["imu1"], "rotationX", 30),
            "twi0.imu1 AngularRateX 30",
        )

    def test_variant_attrs_become_property_sets(self) -> None:
        from bench.renode import part_attr_commands

        commands = part_attr_commands(imu_task(), {"imu1": {"accelZ": 1.0}})
        self.assertEqual(commands, ["twi0.imu1 AccelerationZ 1"])

    def test_unknown_attr_control_rejected(self) -> None:
        from bench.renode import part_attr_commands

        with self.assertRaises(RenodeConfigError):
            part_attr_commands(imu_task(), {"imu1": {"distance": 5}})

    def test_reserved_part_id_rejected(self) -> None:
        from bench.renode import renode_parts

        task = imu_task()
        task.data["fixture"]["components"][0]["id"] = "rtc1"
        with self.assertRaises(RenodeConfigError) as ctx:
            renode_parts(task)
        self.assertIn("collides", str(ctx.exception))

    def test_ds1307_plugin_included_in_resc(self) -> None:
        task = TaskConfig(
            path=Path("tasks/zephyr_nano33ble/level2/ds1307_rtc.yaml"),
            data={
                "task_id": "ds1307_rtc",
                "platform": "zephyr_nano33ble",
                "level": "level2",
                "fixture": {
                    "family": "composite",
                    "components": [
                        {
                            "type": "ds1307",
                            "id": "extrtc1",
                            "bus": "twi0",
                            "attrs": {"initTime": "2026-02-02T15:37:00Z"},
                        }
                    ],
                },
                "validator": {"family": "serial_regex_sequence", "params": {}},
                "simulation": {"timeout_ms": 1500},
                "case": {"id": "ds1307-rtc-renode-nano33", "sketch_name": "ds1307_rtc"},
            },
        )
        resc = generate_resc(
            task,
            repl_relpath="case.repl",
            elf_relpath="artifacts/build/zephyr/zephyr.elf",
            serial_abspath=r"C:\abs\serial.log",
            vcd_abspath=None,
            scenario=None,
            timeout_ms=1500,
        )
        self.assertIn("DS1307.cs", resc.splitlines()[1])
        self.assertIn('twi0.extrtc1 InitTime "2026-02-02T15:37:00Z"', resc)
        # Variant attrs override the fixture seed.
        resc_variant = generate_resc(
            task,
            repl_relpath="case.repl",
            elf_relpath="artifacts/build/zephyr/zephyr.elf",
            serial_abspath=r"C:\abs\serial.log",
            vcd_abspath=None,
            scenario=None,
            timeout_ms=1500,
            variant_attrs={"extrtc1": {"initTime": "2026-07-19T08:03:00Z"}},
        )
        self.assertIn('twi0.extrtc1 InitTime "2026-07-19T08:03:00Z"', resc_variant)
        self.assertNotIn("2026-02-02", resc_variant)


def bme280_task() -> TaskConfig:
    return TaskConfig(
        path=Path("tasks/zephyr_nano33ble/level2/bme280_read_i2c.yaml"),
        data={
            "task_id": "bme280_read_i2c",
            "platform": "zephyr_nano33ble",
            "level": "level2",
            "fixture": {
                "family": "composite",
                "components": [
                    {
                        "type": "bme280",
                        "id": "bme1",
                        "bus": "twi0",
                        "address": "0x76",
                        "attrs": {"temperatureC": "24.5", "humidityRH": "55.0"},
                    }
                ],
            },
            "validator": {"family": "bme280_environment", "params": {}},
            "simulation": {"timeout_ms": 1600},
            "case": {"id": "bme280-read-i2c-renode-nano33", "sketch_name": "bme280_read_i2c"},
        },
    )


class Bme280PartTests(unittest.TestCase):
    def test_repl_declares_native_model(self) -> None:
        repl = generate_repl(bme280_task())
        self.assertIn("bme1: I2C.BME280 @ twi0 0x76", repl)

    def test_fixture_attrs_become_property_sets(self) -> None:
        from bench.renode import part_attr_commands

        commands = part_attr_commands(bme280_task())
        self.assertEqual(
            commands,
            ["twi0.bme1 Humidity 55", "twi0.bme1 Temperature 24.5"],
        )

    def test_variant_attrs_override_fixture_seed(self) -> None:
        from bench.renode import part_attr_commands

        commands = part_attr_commands(
            bme280_task(), {"bme1": {"temperatureC": "31.0", "humidityRH": "42.0"}}
        )
        self.assertEqual(
            commands,
            ["twi0.bme1 Humidity 42", "twi0.bme1 Temperature 31"],
        )

    def test_pressure_control_rejected(self) -> None:
        # The native model's pressure encoder does not invert through the
        # Bosch compensation math (off ~1056x, verified live), so pressurePa
        # must fail the control lint instead of seeding an unsound oracle.
        from bench.renode import part_attr_commands

        with self.assertRaises(RenodeConfigError):
            part_attr_commands(bme280_task(), {"bme1": {"pressurePa": "101325"}})


class CustomProtocolPartTests(unittest.TestCase):
    def test_dht11_repl_and_plugin(self) -> None:
        from bench.config import load_task

        task = load_task("dht11_read", platform="zephyr_nano33ble", level="level2")
        repl = generate_repl(task)
        self.assertIn("dht1: Miscellaneous.IoTBench_DHT11 @ sysbus", repl)
        self.assertIn("Data -> gpio1@11", repl)
        self.assertIn("11 -> dht1@0", repl)
        resc = generate_resc(
            task,
            repl_relpath="case.repl",
            elf_relpath="artifacts/build/zephyr/zephyr.elf",
            serial_abspath=r"C:\abs\serial.log",
            vcd_abspath=None,
            scenario=None,
            timeout_ms=2200,
        )
        self.assertEqual(1, resc.count("DHT11.cs"))
        self.assertIn("dht1 Humidity 40", resc)
        self.assertIn("dht1 Temperature 24", resc)

    def test_ds18b20_scenario_control_and_plugin(self) -> None:
        from bench.config import load_task
        from bench.renode import part_attr_commands

        task = load_task("ds18b20_heat_alarm", platform="zephyr_nano33ble", level="level2")
        repl = generate_repl(task)
        self.assertIn("temp1: Miscellaneous.IoTBench_DS18B20 @ sysbus", repl)
        self.assertIn("Data -> gpio1@11", repl)
        self.assertEqual(["temp1 Temperature 35"], part_attr_commands(task, {"temp1": {"temperature": 35}}))
        resc = generate_resc(
            task,
            repl_relpath="case.repl",
            elf_relpath="artifacts/build/zephyr/zephyr.elf",
            serial_abspath=None,
            vcd_abspath=r"C:\abs\renode.vcd",
            scenario=generate_scenario(task),
            timeout_ms=1500,
        )
        self.assertEqual(1, resc.count("DS18B20.cs"))
        self.assertIn("temp1 Temperature 22", resc)
        self.assertIn("temp1 Temperature 35", resc)

    def test_bme280_spi_repl_plugin_and_variant_attrs(self) -> None:
        from bench.config import load_task
        from bench.renode import part_attr_commands

        task = load_task("bme280_read_spi", platform="zephyr_nano33ble", level="level2")
        repl = generate_repl(task)
        self.assertIn("bme1: SPI.IoTBench_BME280_SPI @ spi2", repl)
        self.assertEqual(
            ["spi2.bme1 Humidity 42", "spi2.bme1 Temperature 31"],
            part_attr_commands(task, {"bme1": {"temperatureC": "31.0", "humidityRH": "42.0"}}),
        )
        resc = generate_resc(
            task,
            repl_relpath="case.repl",
            elf_relpath="artifacts/build/zephyr/zephyr.elf",
            serial_abspath=r"C:\abs\serial.log",
            vcd_abspath=None,
            scenario=None,
            timeout_ms=3000,
        )
        self.assertEqual(1, resc.count("BME280_SPI.cs"))

    def test_unknown_custom_controls_rejected(self) -> None:
        from bench.config import load_task
        from bench.renode import part_attr_commands

        cases = [
            ("dht11_read", "level2", "dht1", {"temperatureC": 24}),
            ("ds18b20_heat_alarm", "level2", "temp1", {"humidity": 50}),
            ("bme280_read_spi", "level2", "bme1", {"pressurePa": 101325}),
        ]
        for task_id, level, part_id, attrs in cases:
            with self.subTest(task=task_id):
                task = load_task(task_id, platform="zephyr_nano33ble", level=level)
                with self.assertRaises(RenodeConfigError):
                    part_attr_commands(task, {part_id: attrs})

    def test_unsupported_protocol_tasks_are_if(self) -> None:
        from bench import cli
        from bench.config import load_task

        for task_id, level in (
            ("dht11_read", "level2"),
            ("dht11_read_button_display", "level3"),
            ("ds18b20_heat_alarm", "level2"),
            ("bme280_read_spi", "level2"),
        ):
            with self.subTest(task=task_id):
                task = load_task(task_id, platform="zephyr_nano33ble", level=level)
                build_payload = cli.build_single_task(
                    task,
                    case_dir=None,
                    sketch_override=None,
                    regenerate=False,
                    arduino_cli="arduino-cli",
                    west="west",
                )
                run_payload = cli.run_single_task(
                    task,
                    case_dir=None,
                    sketch_override=None,
                    use_existing_artifacts=False,
                    regenerate=False,
                    simulation_time_ms=None,
                    arduino_cli="arduino-cli",
                    wokwi_cli="wokwi-cli",
                    west="west",
                    renode_cli="renode",
                    archived_vcd=None,
                )
                self.assertEqual("IF", build_payload["result"])
                self.assertEqual("IF", run_payload["result"])
                self.assertEqual("harness", build_payload["failure_source"])
                self.assertIn("unsupported", run_payload["reason"])

    def test_task_aware_overlay_contains_canonical_aliases(self) -> None:
        from bench.config import load_task
        from bench.runner import zephyr_app_overlay

        dht = zephyr_app_overlay(load_task("dht11_read_button_display", platform="zephyr_nano33ble", level="level3"))
        self.assertIn("data-dht11 = &iotbench_dht11;", dht)
        self.assertIn("my-button = &iotbench_button;", dht)
        self.assertIn("d-7 = &iotbench_lcd_d7;", dht)

        spi = zephyr_app_overlay(load_task("bme280_read_spi", platform="zephyr_nano33ble", level="level2"))
        self.assertIn("&spi2", spi)
        self.assertIn('compatible = "nordic,nrf-spi";', spi)
        self.assertIn("my-sensor = &bme1;", spi)


class ManifestTests(unittest.TestCase):
    def test_verification_manifest_records_resc_and_zephyr_tools(self) -> None:
        from bench import runner

        task = blink_task()
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / task.case_id
            paths = case_paths_from_task(task, case_dir)
            (case_dir).mkdir(parents=True)
            paths.diagram.write_text("// repl\n", encoding="utf-8")
            paths.resc.write_text("# resc\n", encoding="utf-8")
            paths.sketch.mkdir(parents=True)
            (paths.sketch / "src").mkdir()
            (paths.sketch / "src" / "main.c").write_text("int main(void){}\n", encoding="utf-8")
            elf_dir = paths.build_dir / "zephyr"
            elf_dir.mkdir(parents=True)
            (elf_dir / "zephyr.elf").write_text("elf", encoding="utf-8")
            (elf_dir / "zephyr.hex").write_text("hex", encoding="utf-8")
            paths.vcd.parent.mkdir(parents=True)
            paths.vcd.write_text("$timescale 1 us $end\n", encoding="utf-8")

            with mock.patch.object(runner, "command_version", return_value="vX"), mock.patch.object(
                runner.renode, "zephyr_revision", return_value="deadbeef"
            ):
                manifest_path = runner.write_verification(
                    task,
                    paths,
                    {"result": "BC", "classification": "PASS", "reason": "ok", "metrics": {}},
                    command="run",
                )
            import json

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["renode_version"], "vX")
            self.assertEqual(manifest["west_version"], "vX")
            self.assertEqual(manifest["zephyr_revision"], "deadbeef")
            self.assertIsNotNone(manifest["resc_hash"])
            self.assertEqual(manifest["resc_path"], "case.resc")
            self.assertIsNotNone(manifest["diagram_hash"])


class ZephyrSubmissionNormalizationTests(unittest.TestCase):
    """A full project submission contributes only src/; everything Zephyr's
    build system would auto-include (boards/ overlays and conf fragments,
    app-dir Kconfig, presets) must be dropped so the harness-owned build
    configuration cannot be altered by a submission."""

    def normalize(self, populate) -> Path:
        from bench.runner import normalize_zephyr_submission

        task = blink_task()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        source = root / "submission"
        (source / "src").mkdir(parents=True)
        populate(source)
        return normalize_zephyr_submission(task, source, root / "normalized")

    def test_project_submission_keeps_only_src(self) -> None:
        def populate(source: Path) -> None:
            (source / "src" / "main.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
            (source / "src" / "helper.h").write_text("#define X 1\n", encoding="utf-8")
            boards = source / "boards"
            boards.mkdir()
            (boards / "arduino_nano_33_ble.overlay").write_text("/* hijack */\n", encoding="utf-8")
            (boards / "arduino_nano_33_ble.conf").write_text("CONFIG_BOOT_BANNER=y\n", encoding="utf-8")
            (source / "Kconfig").write_text("source \"Kconfig.zephyr\"\n", encoding="utf-8")
            (source / "prj.conf").write_text("CONFIG_EVIL=y\n", encoding="utf-8")
            (source / "app.overlay").write_text("/* hijack */\n", encoding="utf-8")
            (source / "CMakeLists.txt").write_text("# hijack\n", encoding="utf-8")

        destination = self.normalize(populate)
        self.assertTrue((destination / "src" / "main.c").exists())
        self.assertTrue((destination / "src" / "helper.h").exists())
        self.assertFalse((destination / "boards").exists())
        self.assertFalse((destination / "Kconfig").exists())
        from bench.runner import zephyr_app_overlay, zephyr_prj_conf, zephyr_root_cmake

        task = blink_task()
        self.assertEqual(
            (destination / "CMakeLists.txt").read_text(encoding="utf-8"), zephyr_root_cmake(task)
        )
        self.assertEqual((destination / "prj.conf").read_text(encoding="utf-8"), zephyr_prj_conf())
        self.assertEqual(
            (destination / "app.overlay").read_text(encoding="utf-8"), zephyr_app_overlay()
        )

    def test_project_without_main_c_is_compile_fail(self) -> None:
        from bench.runner import COMPILE_FAIL, BuildSimulationError

        def populate(source: Path) -> None:
            (source / "src" / "app.c").write_text("int main(void){return 0;}\n", encoding="utf-8")

        with self.assertRaises(BuildSimulationError) as ctx:
            self.normalize(populate)
        self.assertEqual(ctx.exception.classification, COMPILE_FAIL)

    def test_harness_cmake_compiles_every_src_c_file(self) -> None:
        # Static gates scan all submitted sources; compiling all of src/*.c
        # (like arduino-cli compiles the whole sketch dir) keeps a
        # pattern-stuffed decoy file from satisfying a gate without at least
        # surviving the compiler.
        from bench.runner import zephyr_root_cmake

        cmake = zephyr_root_cmake(blink_task())
        self.assertIn("file(GLOB app_sources CONFIGURE_DEPENDS src/*.c)", cmake)
        self.assertIn("target_sources(app PRIVATE ${app_sources})", cmake)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from bench.config import TaskConfig
from bench.diagrams import validate_diagram_file
from bench.runner import CasePaths, apply_variant_attrs, deep_merge, validate_case
from bench.validators import validate_task


def bme_task(case_dir: Path) -> tuple[TaskConfig, CasePaths]:
    task = TaskConfig(
        path=case_dir / "task.yaml",
        data={
            "task_id": "bme280_read_i2c",
            "fixture": {"family": "composite", "components": []},
            "validator": {
                "family": "bme280_environment",
                "params": {
                    "expected_temperature_c": 24.5,
                    "expected_humidity_rh": 55.0,
                },
            },
            "simulation_variants": [
                {
                    "id": "scenario_a",
                    "attrs": {"bme1": {"temperatureC": "24.5", "humidityRH": "55.0"}},
                    "validator": {"params": {"expected_temperature_c": 24.5, "expected_humidity_rh": 55.0}},
                },
                {
                    "id": "scenario_b",
                    "attrs": {"bme1": {"temperatureC": "31.0", "humidityRH": "42.0"}},
                    "validator": {"params": {"expected_temperature_c": 31.0, "expected_humidity_rh": 42.0}},
                },
            ],
            "simulation": {"require_distinct_variant_outputs": True},
            "case": {"id": case_dir.name, "sketch_name": "bme280_read_i2c"},
        },
    )
    paths = CasePaths(
        task_id="bme280_read_i2c",
        case_id=case_dir.name,
        case_dir=case_dir,
        sketch=case_dir / "sketch" / "bme280_read_i2c",
        diagram=case_dir / "diagram.json",
        wokwi_toml=case_dir / "wokwi.toml",
        build_dir=case_dir / "artifacts" / "build",
        fqbn="arduino:avr:mega",
        serial_log=case_dir / "artifacts" / "serial" / "serial.log",
    )
    return task, paths


class Bme280VariantSupportTests(unittest.TestCase):
    def test_variant_attrs_patch_without_mutating_base_diagram(self):
        diagram = {
            "parts": [
                {"type": "wokwi-arduino-mega", "id": "mega", "attrs": {}},
                {"type": "chip-bme280", "id": "bme1", "attrs": {"temperatureC": "24.5", "humidityRH": "55.0"}},
            ],
            "connections": [],
        }

        patched = apply_variant_attrs(diagram, {"bme1": {"temperatureC": "31.0"}})

        self.assertEqual(diagram["parts"][1]["attrs"]["temperatureC"], "24.5")
        self.assertEqual(patched["parts"][1]["attrs"]["temperatureC"], "31.0")
        self.assertEqual(patched["parts"][1]["attrs"]["humidityRH"], "55.0")

    def test_deep_merge_merges_composite_check_params_by_index(self):
        base = {
            "family": "composite",
            "checks": [
                {"family": "static_checks", "params": {"required_patterns": ["pulseIn"]}},
                {"family": "serial_observation_sequence", "params": {"observations": [{"label": "far"}]}},
            ],
        }
        override = {"checks": [{}, {"params": {"observations": [{"label": "near"}]}}]}

        merged = deep_merge(base, override)

        self.assertEqual(merged["checks"][0]["params"]["required_patterns"], ["pulseIn"])
        self.assertEqual(merged["checks"][1]["params"]["observations"], [{"label": "near"}])

    def test_bme_serial_validator_accepts_expected_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)
            paths.serial_log.write_text("Temperature: 24.6 C Humidity: 54.2 %\n", encoding="utf-8")

            result = validate_task(task, paths)

            self.assertEqual(result.classification, "PASS", result)

    def test_bme_serial_validator_rejects_missing_temperature_or_humidity(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)

            paths.serial_log.write_text("Humidity: 55.0 %\n", encoding="utf-8")
            self.assertEqual(validate_task(task, paths).classification, "FAIL")

            paths.serial_log.write_text("Temperature: 24.5 C\n", encoding="utf-8")
            self.assertEqual(validate_task(task, paths).classification, "FAIL")

    def test_hardcoded_serial_output_fails_multi_variant_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            serial_dir = case_dir / "artifacts" / "serial"
            serial_dir.mkdir(parents=True)
            (serial_dir / "scenario_a.serial.log").write_text(
                "Temperature: 24.0 C Humidity: 40.0 %\n", encoding="utf-8"
            )
            (serial_dir / "scenario_b.serial.log").write_text(
                "Temperature: 24.0 C Humidity: 40.0 %\n", encoding="utf-8"
            )

            result = validate_case(task, paths)

            self.assertEqual(result["classification"], "FAIL", result)
            self.assertIn("scenario_a", result["reason"])

    def test_pressure_within_tolerance_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            task.data["validator"]["params"]["expected_pressure_pa"] = 101325
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)
            paths.serial_log.write_text(
                "Temperature: 24.5 C Humidity: 55.0 % Pressure: 101300 Pa\n", encoding="utf-8"
            )

            self.assertEqual(validate_task(task, paths).classification, "PASS")

    def test_missing_pressure_fails_when_expected(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            task.data["validator"]["params"]["expected_pressure_pa"] = 101325
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)
            paths.serial_log.write_text("Temperature: 24.5 C Humidity: 55.0 %\n", encoding="utf-8")

            result = validate_task(task, paths)

            self.assertEqual(result.classification, "FAIL")
            self.assertIn("pressure", result.reason)

    def test_judged_quantities_pressure_subset_ignores_humidity(self):
        # ESP-IDF design: judge pressure + temperature only. A serial log with
        # temperature + pressure but NO humidity must PASS.
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            task.data["validator"]["params"]["judged_quantities"] = ["temperature", "pressure"]
            task.data["validator"]["params"]["expected_pressure_pa"] = 101325
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)
            paths.serial_log.write_text(
                "Temperature: 24.5 C Pressure: 101300 Pa\n", encoding="utf-8"
            )
            self.assertEqual(validate_task(task, paths).classification, "PASS")

    def test_judged_quantities_humidity_subset_ignores_pressure(self):
        # Arduino/Zephyr design: judge humidity + temperature only. A serial log
        # with temperature + humidity but NO pressure must PASS even though an
        # expected_pressure_pa value is present in params (inert when not judged).
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            task.data["validator"]["params"]["judged_quantities"] = ["temperature", "humidity"]
            task.data["validator"]["params"]["expected_pressure_pa"] = 101325
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)
            paths.serial_log.write_text("Temperature: 24.5 C Humidity: 55.0 %\n", encoding="utf-8")
            self.assertEqual(validate_task(task, paths).classification, "PASS")

    def test_judged_quantities_still_fails_missing_judged_dimension(self):
        # Judging pressure: a log missing pressure must still FAIL.
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            task.data["validator"]["params"]["judged_quantities"] = ["temperature", "pressure"]
            task.data["validator"]["params"]["expected_pressure_pa"] = 101325
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)
            paths.serial_log.write_text("Temperature: 24.5 C Humidity: 55.0 %\n", encoding="utf-8")
            result = validate_task(task, paths)
            self.assertEqual(result.classification, "FAIL")
            self.assertIn("pressure", result.reason)

    def test_wrong_pressure_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            task.data["validator"]["params"]["expected_pressure_pa"] = 101325
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)
            paths.serial_log.write_text(
                "Temperature: 24.5 C Humidity: 55.0 % Pressure: 99000 Pa\n", encoding="utf-8"
            )

            self.assertEqual(validate_task(task, paths).classification, "FAIL")

    def test_pressure_expectation_falls_back_to_variant_attr(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            task.data["validator"]["params"] = {}
            task.data["active_simulation_variant"] = {
                "id": "scenario_a",
                "attrs": {"bme1": {"temperatureC": "24.5", "humidityRH": "55.0", "pressurePa": "101325"}},
            }
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)

            paths.serial_log.write_text(
                "Temperature: 24.5 C Humidity: 55.0 % Pressure: 101325 Pa\n", encoding="utf-8"
            )
            self.assertEqual(validate_task(task, paths).classification, "PASS")

            paths.serial_log.write_text("Temperature: 24.5 C Humidity: 55.0 %\n", encoding="utf-8")
            self.assertEqual(validate_task(task, paths).classification, "FAIL")

    def test_pressure_not_required_when_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            assert paths.serial_log is not None
            paths.serial_log.parent.mkdir(parents=True)
            paths.serial_log.write_text("Temperature: 24.5 C Humidity: 55.0 %\n", encoding="utf-8")

            self.assertEqual(validate_task(task, paths).classification, "PASS")

    def test_identical_numeric_outputs_with_different_text_fail_distinctness(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            task, paths = bme_task(case_dir)
            # Both variants accept their own values, but the firmware printed
            # the same numbers with cosmetic differences -> distinctness fail.
            task.data["simulation_variants"][0]["validator"]["params"] = {
                "expected_temperature_c": 24.5,
                "expected_humidity_rh": 55.0,
                "temperature_tolerance_c": 50.0,
                "humidity_tolerance_rh": 50.0,
            }
            task.data["simulation_variants"][1]["validator"]["params"] = {
                "expected_temperature_c": 31.0,
                "expected_humidity_rh": 42.0,
                "temperature_tolerance_c": 50.0,
                "humidity_tolerance_rh": 50.0,
            }
            task.data["validator"]["params"]["temperature_tolerance_c"] = 50.0
            task.data["validator"]["params"]["humidity_tolerance_rh"] = 50.0
            serial_dir = case_dir / "artifacts" / "serial"
            serial_dir.mkdir(parents=True)
            (serial_dir / "scenario_a.serial.log").write_text(
                "Temperature: 28.0 C Humidity: 50.0 %\n", encoding="utf-8"
            )
            (serial_dir / "scenario_b.serial.log").write_text(
                "Temp reading: 28.0 C / RH: 50.0 %\n", encoding="utf-8"
            )

            result = validate_case(task, paths)

            self.assertEqual(result["classification"], "FAIL", result)
            self.assertIn("identical numeric outputs", result["reason"], result)

    def test_custom_bme280_chip_part_lints_with_case_local_binary_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            chip_dir = case_dir / "chips"
            chip_dir.mkdir()
            (chip_dir / "bme280.chip.wasm").write_bytes(b"wasm")
            (chip_dir / "bme280.chip.json").write_text("{}", encoding="utf-8")
            (case_dir / "wokwi.toml").write_text(
                "[wokwi]\nversion = 1\n\n[[chip]]\nname = 'bme280'\nbinary = 'chips/bme280.chip.wasm'\n",
                encoding="utf-8",
            )
            (case_dir / "diagram.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "parts": [
                            {"type": "wokwi-arduino-mega", "id": "mega", "attrs": {}},
                            {"type": "chip-bme280", "id": "bme1", "attrs": {}},
                        ],
                        "connections": [],
                    }
                ),
                encoding="utf-8",
            )
            task = TaskConfig(
                path=case_dir / "task.yaml",
                data={
                    "task_id": "bme280_read_i2c",
                    "fixture": {"family": "composite", "components": []},
                    "validator": {"family": "bme280_environment", "params": {}},
                    "custom_chips": [{"name": "bme280", "binary": "chips/bme280.chip.wasm"}],
                    "case": {"id": "case", "sketch_name": "sketch"},
                },
            )

            validate_diagram_file(case_dir / "diagram.json", task)


if __name__ == "__main__":
    unittest.main()

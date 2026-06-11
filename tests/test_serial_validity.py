import tempfile
import unittest
from pathlib import Path

from bench.config import load_task
from bench.results import FAIL, PASS
from bench.runner import CasePaths
from bench.validators import validate_task


class SerialValidityTests(unittest.TestCase):
    def test_pir_sequence_must_follow_configured_state_order(self):
        self.assertSerialClassification(
            "sensor_pir_human_motion",
            "No Motion Detected!\nMotion Detected!\nNo Motion Detected!\n",
            PASS,
        )

        self.assertSerialClassification(
            "sensor_pir_human_motion",
            "Motion Detected!\nNo Motion Detected!\n",
            FAIL,
        )

    def test_button_press_response_count_must_match_press_scenario(self):
        self.assertSerialClassification(
            "button_status_display",
            "Button Pressed!\nButton Pressed!\n",
            PASS,
        )

        self.assertSerialClassification(
            "button_status_display",
            "Button Pressed!\nButton Pressed!\nButton Pressed!\n",
            FAIL,
        )

    def test_tmp36_temperatures_must_appear_as_ordered_observations(self):
        self.assertSerialClassification(
            "tmp36_read",
            "24.8\n24.8\n-0.1\n-0.1\n24.8\n24.8\n",
            PASS,
        )

        self.assertSerialClassification(
            "tmp36_read",
            "25.0\n25.0\n0.0\n0.0\n",
            FAIL,
        )

        self.assertSerialClassification(
            "tmp36_read",
            "debug values: 0.0 25.0\n",
            FAIL,
        )

    def assertSerialClassification(self, task_id: str, serial_text: str, expected: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            serial_log = root / "serial.log"
            serial_log.write_text(serial_text, encoding="utf-8")
            # These cases exercise the serial oracle; provide a sketch that
            # satisfies the tasks' static gates so they are not what fails.
            sketch_dir = root / "sketch"
            sketch_dir.mkdir()
            (sketch_dir / "sketch.ino").write_text(
                "void setup(){ pinMode(2, INPUT); }\n"
                "void loop(){ digitalRead(2); analogRead(A0); millis(); }\n",
                encoding="utf-8",
            )
            task = load_task(task_id)
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
            self.assertEqual(result.classification, expected, result.payload())


if __name__ == "__main__":
    unittest.main()

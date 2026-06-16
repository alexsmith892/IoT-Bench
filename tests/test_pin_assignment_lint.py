"""Fixture components must not share a GPIO unless the sharing is electrically
legitimate (a scanned keypad matrix). A button driving the same pin as an LCD
register-select, an I2C clock colliding with an LCD data line, or a relay on a
keypad column are wiring faults that make a case unrunnable -- the harness's own
reference solution cannot satisfy two conflicting roles on one pin, so the case
can never produce a sound BC/BF judgment.

Analyzer channels are excluded on purpose: a logic-analyzer probe legitimately
shares the pin of the component it observes. Matrix keypad parts legitimately
share row lines with other row lines and column lines with other column lines,
so all ``matrix_key`` parts collapse to a single logical owner; we still require
the row-pin set and column-pin set to stay disjoint (a row==column pin would be
a short).
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from bench.config import iter_tasks
from bench.runner import generate_case


def _component_owner(component: dict) -> str:
    if component.get("type") == "matrix_key":
        return "<keypad-matrix>"
    return str(component.get("id"))


def _fixture_pin_owners(fixture: dict) -> tuple[dict[str, set[str]], set[str], set[str]]:
    pin_owners: dict[str, set[str]] = {}
    keypad_rows: set[str] = set()
    keypad_cols: set[str] = set()
    for component in fixture.get("components", []) or []:
        if not isinstance(component, dict):
            continue
        owner = _component_owner(component)
        pins: list[str] = []
        if "pin" in component:
            pins.append(str(component["pin"]))
        named = component.get("pins")
        if isinstance(named, dict):
            for role, value in named.items():
                pins.append(str(value))
                if component.get("type") == "matrix_key":
                    (keypad_rows if role == "row" else keypad_cols).add(str(value))
        for pin in pins:
            pin_owners.setdefault(pin, set()).add(owner)
    return pin_owners, keypad_rows, keypad_cols


def _component_gpio_pins(fixture: dict) -> set[str]:
    pins: set[str] = set()
    for component in fixture.get("components", []) or []:
        if not isinstance(component, dict):
            continue
        if "pin" in component:
            pins.add(str(component["pin"]))
        named = component.get("pins")
        if isinstance(named, dict):
            pins.update(str(value) for value in named.values())
    return {pin for pin in pins if pin.isdigit()}


def _analyzer_gpio_pins(fixture: dict) -> set[str]:
    analyzer = fixture.get("analyzer")
    if not isinstance(analyzer, dict):
        return set()
    channels = analyzer.get("channels")
    if not isinstance(channels, list):
        return set()
    return {
        str(channel.get("pin"))
        for channel in channels
        if isinstance(channel, dict) and str(channel.get("pin", "")).isdigit()
    }


def _diagram_esp_pins(diagram_path: Path) -> set[str]:
    diagram = json.loads(diagram_path.read_text(encoding="utf-8"))
    pins: set[str] = set()
    for connection in diagram.get("connections", []) or []:
        if not isinstance(connection, list):
            continue
        for endpoint in connection[:2]:
            if isinstance(endpoint, str) and endpoint.startswith("esp:"):
                pins.add(endpoint.split(":", 1)[1])
    return pins


class PinAssignmentLintTests(unittest.TestCase):
    def test_no_fixture_components_share_a_gpio(self):
        for platform in ("arduino_mega", "esp32s3_espidf", "zephyr_nano33ble"):
            for level in ("level1", "level2", "level3"):
                for task in iter_tasks(platform=platform, level=level):
                    fixture = task.data.get("fixture")
                    if not isinstance(fixture, dict):
                        continue
                    with self.subTest(platform=platform, task=task.task_id):
                        pin_owners, rows, cols = _fixture_pin_owners(fixture)
                        shared = {
                            pin: sorted(owners)
                            for pin, owners in pin_owners.items()
                            if len(owners) > 1
                        }
                        self.assertEqual(
                            shared,
                            {},
                            f"{platform}/{task.task_id}: GPIO shared by distinct "
                            f"components {shared}",
                        )
                        overlap = rows & cols
                        self.assertEqual(
                            overlap,
                            set(),
                            f"{platform}/{task.task_id}: keypad pin(s) {overlap} "
                            "used as both row and column (short)",
                        )

    def test_esp32_fixture_gpios_are_named_in_prompt(self):
        for level in ("level1", "level2", "level3"):
            for task in iter_tasks(platform="esp32s3_espidf", level=level):
                fixture = task.data.get("fixture")
                if not isinstance(fixture, dict):
                    continue
                prompt = task.prompt_text
                pins: set[str] = set()
                for component in fixture.get("components", []) or []:
                    if not isinstance(component, dict):
                        continue
                    if "pin" in component:
                        pins.add(str(component["pin"]))
                    named = component.get("pins")
                    if isinstance(named, dict):
                        pins.update(str(value) for value in named.values())
                with self.subTest(level=level, task=task.task_id):
                    missing = sorted(
                        pin
                        for pin in pins
                        if pin.isdigit()
                        and not re.search(rf"(?<!\d){re.escape(pin)}(?!\d)", prompt)
                    )
                    self.assertEqual(
                        missing,
                        [],
                        f"esp32s3_espidf/{task.task_id}: fixture GPIO(s) not named in prompt",
                    )

    def test_esp32_generated_diagrams_wire_fixture_and_analyzer_gpios(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for level in ("level1", "level2", "level3"):
                for task in iter_tasks(platform="esp32s3_espidf", level=level):
                    fixture = task.data.get("fixture")
                    if not isinstance(fixture, dict) or not task.is_supported:
                        continue
                    with self.subTest(level=level, task=task.task_id):
                        paths = generate_case(task, root=root)
                        diagram_pins = _diagram_esp_pins(paths.diagram)
                        expected_pins = _component_gpio_pins(fixture) | _analyzer_gpio_pins(fixture)
                        missing = sorted(expected_pins - diagram_pins)
                        self.assertEqual(
                            missing,
                            [],
                            f"esp32s3_espidf/{task.task_id}: generated diagram does not "
                            f"wire fixture/analyzer GPIO(s) {missing}",
                        )

    def test_esp32_known_simulator_deviations_are_documented(self):
        docs = (
            Path("docs") / "esp32s3-task-status.md"
        ).read_text(encoding="utf-8")
        expectations = {
            "safebox": ["GPIO 12", "GPIO 8"],
            "GPIO remap": ["GPIO 43/44", "GPIO 45/46"],
            "DHT surrogate": ["DHT11", "DHT22"],
            "RTC surrogate": ["DS3231", "DS1307", "temperature"],
            "keypad surrogate": ["partial matrix"],
        }
        for label, tokens in expectations.items():
            with self.subTest(deviation=label):
                for token in tokens:
                    self.assertIn(token, docs)

    def test_esp32_safebox_relay_uses_gpio12_and_keypad_column_moves_to_gpio8(self):
        for task_id in ("safebox", "safebox_display"):
            task = next(
                task
                for task in iter_tasks(platform="esp32s3_espidf", level="level3")
                if task.task_id == task_id
            )
            components = task.fixture.get("components", []) or []
            relay = next(component for component in components if component.get("type") == "relay")
            keypad_cols = {
                str(component.get("pins", {}).get("col"))
                for component in components
                if component.get("type") == "matrix_key"
            }
            with self.subTest(task=task_id):
                self.assertEqual(str(relay.get("pin")), "12")
                self.assertIn("8", keypad_cols)
                self.assertNotIn("12", keypad_cols)


if __name__ == "__main__":
    unittest.main()

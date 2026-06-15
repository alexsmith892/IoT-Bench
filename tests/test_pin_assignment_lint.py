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

import unittest

from bench.config import iter_tasks


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


if __name__ == "__main__":
    unittest.main()

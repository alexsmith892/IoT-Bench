"""Deterministic Wokwi diagram generation and lightweight linting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import TaskConfig


class DiagramError(Exception):
    """Raised when a diagram cannot be generated or fails local checks."""


def part(
    part_type: str,
    part_id: str,
    *,
    left: int,
    top: int,
    attrs: dict[str, Any] | None = None,
    rotate: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": part_type,
        "id": part_id,
        "top": top,
        "left": left,
        "attrs": attrs or {},
    }
    if rotate is not None:
        result["rotate"] = rotate
    return result


def connection(a: str, b: str, color: str) -> list[Any]:
    return [a, b, color, []]


def generate_diagram(task: TaskConfig) -> dict[str, Any]:
    generators = {
        "single_led_output": single_led_output,
        "dual_led_output": dual_led_output,
        "button_to_buzzer": button_to_buzzer,
        "button_serial": button_serial,
        "pir_serial": pir_serial,
        "analog_temperature_serial": analog_temperature_serial,
    }
    try:
        return generators[task.fixture_family](task)
    except KeyError as exc:
        raise DiagramError(f"unknown fixture family: {task.fixture_family}") from exc


def base_diagram() -> dict[str, Any]:
    return {
        "version": 1,
        "author": "IoT-Bench",
        "editor": "wokwi",
        "parts": [
            part("wokwi-arduino-mega", "mega", left=20, top=120),
        ],
        "connections": [],
        "dependencies": {},
    }


def single_led_output(task: TaskConfig) -> dict[str, Any]:
    pin = str(task.fixture.get("pins", {}).get("led", "3"))
    diagram = base_diagram()
    diagram["parts"].extend(
        [
            part("wokwi-resistor", "r1", left=115, top=67, rotate=90, attrs={"value": "220"}),
            part("wokwi-led", "led1", left=120, top=0, attrs={"color": "red"}),
            logic_analyzer(task),
        ]
    )
    diagram["connections"].extend(
        [
            connection("mega:GND.1", "led1:C", "black"),
            connection("r1:1", "led1:A", "blue"),
            connection(f"mega:{pin}", "r1:2", "blue"),
            connection("logic1:GND", "mega:GND.1", "black"),
        ]
    )
    add_analyzer_connections(diagram, task)
    return diagram


def dual_led_output(task: TaskConfig) -> dict[str, Any]:
    pins = task.fixture.get("pins", {})
    pin1 = str(pins.get("led1", "2"))
    pin2 = str(pins.get("led2", "3"))
    diagram = base_diagram()
    diagram["parts"].extend(
        [
            part("wokwi-resistor", "r1", left=110, top=28, rotate=90, attrs={"value": "220"}),
            part("wokwi-led", "led1", left=115, top=-38, attrs={"color": "red"}),
            part("wokwi-resistor", "r2", left=195, top=28, rotate=90, attrs={"value": "220"}),
            part("wokwi-led", "led2", left=200, top=-38, attrs={"color": "green"}),
            logic_analyzer(task),
        ]
    )
    diagram["connections"].extend(
        [
            connection("mega:GND.1", "led1:C", "black"),
            connection("mega:GND.1", "led2:C", "black"),
            connection("r1:1", "led1:A", "blue"),
            connection("r2:1", "led2:A", "blue"),
            connection(f"mega:{pin1}", "r1:2", "blue"),
            connection(f"mega:{pin2}", "r2:2", "green"),
            connection("logic1:GND", "mega:GND.1", "black"),
        ]
    )
    add_analyzer_connections(diagram, task)
    return diagram


def button_to_buzzer(task: TaskConfig) -> dict[str, Any]:
    pins = task.fixture.get("pins", {})
    button_pin = str(pins.get("button", "2"))
    buzzer_pin = str(pins.get("buzzer", "13"))
    diagram = base_diagram()
    diagram["parts"].extend(
        [
            button_part(task, "btn1", left=150, top=-35),
            part("wokwi-resistor", "r1", left=198, top=50, rotate=90, attrs={"value": "10000"}),
            part("wokwi-buzzer", "buzzer1", left=315, top=35, attrs={"volume": "0.2"}),
            logic_analyzer(task),
        ]
    )
    diagram["connections"].extend(
        active_high_button_connections("btn1", "r1", button_pin)
        + [
            connection("buzzer1:1", "mega:GND.1", "black"),
            connection("buzzer1:2", f"mega:{buzzer_pin}", "red"),
            connection("logic1:GND", "mega:GND.1", "black"),
        ]
    )
    add_analyzer_connections(diagram, task)
    return diagram


def button_serial(task: TaskConfig) -> dict[str, Any]:
    button_pin = str(task.fixture.get("pins", {}).get("button", "2"))
    diagram = base_diagram()
    diagram["parts"].extend(
        [
            button_part(task, "btn1", left=150, top=-35),
            part("wokwi-resistor", "r1", left=198, top=50, rotate=90, attrs={"value": "10000"}),
        ]
    )
    diagram["connections"].extend(active_high_button_connections("btn1", "r1", button_pin))
    return diagram


def pir_serial(task: TaskConfig) -> dict[str, Any]:
    pin = str(task.fixture.get("pins", {}).get("pir", "4"))
    diagram = base_diagram()
    attrs = {"color": "orange", "label": "PIR emu", "bounce": "0"}
    diagram["parts"].extend(
        [
            part("wokwi-pushbutton", "pir1", left=150, top=-35, attrs=attrs),
            part("wokwi-resistor", "r1", left=198, top=50, rotate=90, attrs={"value": "10000"}),
        ]
    )
    diagram["connections"].extend(active_high_button_connections("pir1", "r1", pin))
    return diagram


def analog_temperature_serial(task: TaskConfig) -> dict[str, Any]:
    pin = str(task.fixture.get("pins", {}).get("analog", "A0"))
    initial = task.fixture.get("analog_source", {}).get("initial_value", 153)
    diagram = base_diagram()
    diagram["parts"].append(
        part("wokwi-potentiometer", "pot1", left=150, top=-25, attrs={"value": str(initial)})
    )
    diagram["connections"].extend(
        [
            connection("pot1:GND", "mega:GND.1", "black"),
            connection("pot1:VCC", "mega:5V", "red"),
            connection("pot1:SIG", f"mega:{pin}", "green"),
        ]
    )
    return diagram


def logic_analyzer(task: TaskConfig) -> dict[str, Any]:
    attrs = dict(task.fixture.get("analyzer", {}).get("attrs") or {})
    return part("wokwi-logic-analyzer", "logic1", left=300, top=-55, attrs=attrs)


def button_part(task: TaskConfig, part_id: str, *, left: int, top: int) -> dict[str, Any]:
    attrs = {"color": "green", "label": "Press", "bounce": "0"}
    attrs.update(task.fixture.get("button_attrs") or {})
    return part("wokwi-pushbutton", part_id, left=left, top=top, attrs=attrs)


def active_high_button_connections(button_id: str, resistor_id: str, pin: str) -> list[list[Any]]:
    return [
        connection(f"{button_id}:1.r", "mega:5V", "red"),
        connection(f"{button_id}:2.r", f"mega:{pin}", "green"),
        connection(f"{resistor_id}:1", f"mega:{pin}", "green"),
        connection(f"{resistor_id}:2", "mega:GND.1", "black"),
    ]


def add_analyzer_connections(diagram: dict[str, Any], task: TaskConfig) -> None:
    for channel in task.fixture.get("analyzer", {}).get("channels", []):
        diagram["connections"].append(
            connection(f"logic1:{channel['signal']}", f"mega:{channel['pin']}", "green")
        )


def write_diagram(path: Path, diagram: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(diagram, indent=2) + "\n", encoding="utf-8")


def load_diagram(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_diagram_file(path: Path, task: TaskConfig) -> None:
    if not path.exists():
        raise DiagramError(f"diagram.json not found: {path}")
    try:
        diagram = load_diagram(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise DiagramError(f"could not read diagram {path}: {exc}") from exc
    validate_diagram_shape(diagram)
    validate_analyzer_wiring(diagram, task)


def validate_diagram_shape(diagram: dict[str, Any]) -> None:
    part_ids = [part_data.get("id") for part_data in diagram.get("parts", [])]
    if "mega" not in part_ids:
        raise DiagramError("diagram is missing Arduino Mega part id 'mega'")
    if len(part_ids) != len(set(part_ids)):
        raise DiagramError("diagram contains duplicate part ids")
    for item in diagram.get("connections", []):
        if not isinstance(item, list) or len(item) < 2:
            raise DiagramError(f"invalid connection entry: {item!r}")


def validate_analyzer_wiring(diagram: dict[str, Any], task: TaskConfig) -> None:
    channels = task.fixture.get("analyzer", {}).get("channels", [])
    if not channels:
        return

    connections = diagram.get("connections", [])
    endpoints = [{item[0], item[1]} for item in connections if isinstance(item, list) and len(item) >= 2]
    for channel in channels:
        signal = str(channel["signal"])
        pin = str(channel["pin"])
        if not any(
            any(endpoint.endswith(f":{signal}") for endpoint in pair)
            and any(endpoint.endswith(f":{pin}") for endpoint in pair)
            for pair in endpoints
        ):
            raise DiagramError(
                f"logic analyzer {signal} is not wired to GPIO {pin}"
            )
    if not any(
        any(endpoint == "logic1:GND" for endpoint in pair)
        and any(":GND" in endpoint for endpoint in pair)
        for pair in endpoints
    ):
        raise DiagramError("logic analyzer GND is not wired to board GND")

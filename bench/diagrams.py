"""Deterministic Wokwi diagram generation and lightweight linting."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import TaskConfig


class DiagramError(Exception):
    """Raised when a diagram cannot be generated or fails local checks."""


NATIVE_WOKWI_PART_TYPES = {
    "board-bmp180",
    "wokwi-arduino-mega",
    "wokwi-buzzer",
    "wokwi-dht22",
    "wokwi-ds1307",
    "wokwi-ds18b20",
    "wokwi-hc-sr04",
    "wokwi-ky-040",
    "wokwi-lcd1602",
    "wokwi-led",
    "wokwi-logic-analyzer",
    "wokwi-membrane-keypad",
    "wokwi-mpu6050",
    "wokwi-photoresistor-sensor",
    "wokwi-pir-motion-sensor",
    "wokwi-potentiometer",
    "wokwi-pushbutton",
    "wokwi-relay-module",
    "wokwi-resistor",
    "wokwi-analog-joystick",
    "wokwi-ntc-temperature-sensor",
    "wokwi-text",
}


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
        "composite": composite,
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


def composite(task: TaskConfig) -> dict[str, Any]:
    diagram = base_diagram()
    analyzer_channels = task.fixture.get("analyzer", {}).get("channels", [])
    if analyzer_channels:
        diagram["parts"].append(logic_analyzer(task))
        diagram["connections"].append(connection("logic1:GND", "mega:GND.1", "black"))

    for index, component in enumerate(task.fixture.get("components", []), start=1):
        add_component(diagram, task, component, index)

    if analyzer_channels:
        add_analyzer_connections(diagram, task)
    return diagram


def add_component(
    diagram: dict[str, Any], task: TaskConfig, component: dict[str, Any], index: int
) -> None:
    kind = component["type"]
    part_id = component.get("id", f"{kind}{index}")
    left = int(component.get("left", 120 + (index % 4) * 105))
    top = int(component.get("top", -80 + (index // 4) * 95))
    pins = {name: str(value) for name, value in (component.get("pins") or {}).items()}

    if kind == "led":
        resistor_id = component.get("resistor_id", f"r_led_{index}")
        diagram["parts"].extend(
            [
                part("wokwi-resistor", resistor_id, left=left - 5, top=top + 66, rotate=90, attrs={"value": "220"}),
                part("wokwi-led", part_id, left=left, top=top, attrs={"color": component.get("color", "red")}),
            ]
        )
        pin = str(component.get("pin") or pins.get("signal", "3"))
        diagram["connections"].extend(
            [
                connection("mega:GND.1", f"{part_id}:C", "black"),
                connection(f"{resistor_id}:1", f"{part_id}:A", "blue"),
                connection(f"mega:{pin}", f"{resistor_id}:2", "blue"),
            ]
        )
    elif kind in {"active_buzzer", "passive_buzzer", "buzzer"}:
        pin = str(component.get("pin") or pins.get("signal", "3"))
        diagram["parts"].append(
            part("wokwi-buzzer", part_id, left=left, top=top, attrs={"volume": str(component.get("volume", "0.2"))})
        )
        diagram["connections"].extend(
            [
                connection(f"{part_id}:1", "mega:GND.1", "black"),
                connection(f"{part_id}:2", f"mega:{pin}", "red"),
            ]
        )
    elif kind == "relay":
        pin = str(component.get("pin") or pins.get("in", "2"))
        diagram["parts"].append(part("wokwi-relay-module", part_id, left=left, top=top))
        diagram["connections"].extend(
            [
                connection(f"{part_id}:VCC", "mega:5V", "red"),
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
                connection(f"{part_id}:IN", f"mega:{pin}", "green"),
            ]
        )
    elif kind in {"button", "digital_input", "tilt_switch", "sound_sensor", "shock_sensor", "pir_surrogate"}:
        pin = str(component.get("pin") or pins.get("signal", "2"))
        resistor_id = component.get("resistor_id", f"r_btn_{index}")
        attrs = {"color": component.get("color", "green"), "label": component.get("label", kind), "bounce": "0"}
        diagram["parts"].extend(
            [
                part("wokwi-pushbutton", part_id, left=left, top=top, attrs=attrs),
                part("wokwi-resistor", resistor_id, left=left + 48, top=top + 85, rotate=90, attrs={"value": "10000"}),
            ]
        )
        diagram["connections"].extend(active_high_button_connections(part_id, resistor_id, pin))
    elif kind in {"analog_source", "tmp36_surrogate", "photoresistor_surrogate", "water_level_surrogate", "joystick_surrogate"}:
        pin = str(component.get("pin") or pins.get("signal", "A0"))
        initial = component.get("initial_value", component.get("value", 512))
        diagram["parts"].append(
            part("wokwi-potentiometer", part_id, left=left, top=top, attrs={"value": str(initial)})
        )
        diagram["connections"].extend(
            [
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
                connection(f"{part_id}:VCC", "mega:5V", "red"),
                connection(f"{part_id}:SIG", f"mega:{pin}", "green"),
            ]
        )
    elif kind == "photoresistor":
        pin = str(component.get("pin") or pins.get("ao", "A0"))
        diagram["parts"].append(part("wokwi-photoresistor-sensor", part_id, left=left, top=top, attrs=component.get("attrs") or {}))
        diagram["connections"].extend(
            [
                connection(f"{part_id}:VCC", "mega:5V", "red"),
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
                connection(f"{part_id}:AO", f"mega:{pin}", "green"),
            ]
        )
    elif kind == "joystick":
        vert = str(component.get("pin") or pins.get("vert", pins.get("y", "A0")))
        horz = pins.get("horz") or pins.get("x")
        sel = pins.get("sel") or pins.get("button")
        diagram["parts"].append(part("wokwi-analog-joystick", part_id, left=left, top=top, attrs=component.get("attrs") or {}))
        diagram["connections"].extend(
            [
                connection(f"{part_id}:VCC", "mega:5V", "red"),
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
                connection(f"{part_id}:VERT", f"mega:{vert}", "green"),
            ]
        )
        if horz:
            diagram["connections"].append(connection(f"{part_id}:HORZ", f"mega:{horz}", "green"))
        if sel:
            diagram["connections"].append(connection(f"{part_id}:SEL", f"mega:{sel}", "green"))
    elif kind == "rotary_encoder":
        diagram["parts"].append(part("wokwi-ky-040", part_id, left=left, top=top))
        pin_map = {"CLK": "clk", "DT": "dt", "SW": "sw"}
        for part_pin, config_pin in pin_map.items():
            if config_pin in pins:
                diagram["connections"].append(connection(f"{part_id}:{part_pin}", f"mega:{pins[config_pin]}", "green"))
        diagram["connections"].extend(
            [
                connection(f"{part_id}:VCC", "mega:5V", "red"),
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
            ]
        )
    elif kind == "keypad4x4":
        diagram["parts"].append(part("wokwi-membrane-keypad", part_id, left=left, top=top))
        for part_pin in ("R1", "R2", "R3", "R4", "C1", "C2", "C3", "C4"):
            key = part_pin.lower()
            if key in pins:
                diagram["connections"].append(connection(f"{part_id}:{part_pin}", f"mega:{pins[key]}", "green"))
    elif kind == "lcd1602":
        diagram["parts"].append(part("wokwi-lcd1602", part_id, left=left, top=top, attrs=component.get("attrs") or {}))
        lcd_pins = {"RS": "rs", "E": "e", "D4": "d4", "D5": "d5", "D6": "d6", "D7": "d7", "A": "a"}
        diagram["connections"].extend(
            [
                connection(f"{part_id}:VSS", "mega:GND.1", "black"),
                connection(f"{part_id}:VDD", "mega:5V", "red"),
                connection(f"{part_id}:RW", "mega:GND.1", "black"),
                connection(f"{part_id}:K", "mega:GND.1", "black"),
            ]
        )
        for part_pin, config_pin in lcd_pins.items():
            if config_pin in pins:
                diagram["connections"].append(connection(f"{part_id}:{part_pin}", f"mega:{pins[config_pin]}", "green"))
        if "a" not in pins:
            diagram["connections"].append(connection(f"{part_id}:A", "mega:5V", "red"))
    elif kind in {"dht11", "dht22"}:
        pin = str(component.get("pin") or pins.get("data", "14"))
        attrs = {"temperature": str(component.get("temperature", "24")), "humidity": str(component.get("humidity", "40"))}
        diagram["parts"].append(part("wokwi-dht22", part_id, left=left, top=top, attrs=attrs))
        diagram["connections"].extend(
            [
                connection(f"{part_id}:VCC", "mega:5V", "red"),
                connection(f"{part_id}:SDA", f"mega:{pin}", "green"),
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
            ]
        )
    elif kind in {"ds1307", "mpu6050", "bme280_i2c"}:
        part_type = {"ds1307": "wokwi-ds1307", "mpu6050": "wokwi-mpu6050", "bme280_i2c": "board-bme280"}[kind]
        diagram["parts"].append(part(part_type, part_id, left=left, top=top, attrs=component.get("attrs") or {}))
        sda = pins.get("sda", "20")
        scl = pins.get("scl", "21")
        for candidate in ("VCC", "VIN"):
            diagram["connections"].append(connection(f"{part_id}:{candidate}", "mega:5V", "red"))
            break
        diagram["connections"].extend(
            [
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
                connection(f"{part_id}:SDA", f"mega:{sda}", "green"),
                connection(f"{part_id}:SCL", f"mega:{scl}", "green"),
            ]
        )
    elif kind == "bme280_spi":
        diagram["parts"].append(part("board-bme280", part_id, left=left, top=top, attrs=component.get("attrs") or {}))
        spi_map = {"SCK": "sck", "SDO": "miso", "SDI": "mosi", "CS": "cs"}
        diagram["connections"].extend(
            [
                connection(f"{part_id}:VCC", "mega:5V", "red"),
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
            ]
        )
        for part_pin, config_pin in spi_map.items():
            if config_pin in pins:
                diagram["connections"].append(connection(f"{part_id}:{part_pin}", f"mega:{pins[config_pin]}", "green"))
    elif kind == "hcsr04":
        diagram["parts"].append(part("wokwi-hc-sr04", part_id, left=left, top=top, attrs=component.get("attrs") or {}))
        diagram["connections"].extend(
            [
                connection(f"{part_id}:VCC", "mega:5V", "red"),
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
                connection(f"{part_id}:TRIG", f"mega:{pins.get('trig', '9')}", "green"),
                connection(f"{part_id}:ECHO", f"mega:{pins.get('echo', '10')}", "green"),
            ]
        )
    elif kind == "ds18b20":
        pin = pins.get("data", "4")
        diagram["parts"].append(part("wokwi-ds18b20", part_id, left=left, top=top, attrs=component.get("attrs") or {}))
        diagram["connections"].extend(
            [
                connection(f"{part_id}:VCC", "mega:5V", "red"),
                connection(f"{part_id}:GND", "mega:GND.1", "black"),
                connection(f"{part_id}:DQ", f"mega:{pin}", "green"),
            ]
        )
    elif kind == "laser":
        pin = str(component.get("pin") or pins.get("signal", "8"))
        diagram["parts"].append(part("wokwi-led", part_id, left=left, top=top, attrs={"color": "red", "label": "Laser"}))
        diagram["connections"].extend(
            [
                connection(f"{part_id}:C", "mega:GND.1", "black"),
                connection(f"{part_id}:A", f"mega:{pin}", "red"),
            ]
        )
    else:
        raise DiagramError(f"unknown composite component type: {kind}")


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
    validate_part_types(diagram, task, path)
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


def validate_part_types(diagram: dict[str, Any], task: TaskConfig, diagram_path: Path) -> None:
    custom_chips = {f"chip-{chip['name']}": chip for chip in task.custom_chips}
    for item in diagram.get("parts", []):
        part_type = item.get("type")
        if part_type in NATIVE_WOKWI_PART_TYPES:
            continue
        if isinstance(part_type, str) and part_type.startswith("chip-"):
            validate_custom_chip_part(part_type, custom_chips, diagram_path)
            continue
        raise DiagramError(f"unknown Wokwi part type: {part_type!r}")


def validate_custom_chip_part(
    part_type: str,
    custom_chips: dict[str, dict[str, Any]],
    diagram_path: Path,
) -> None:
    chip = custom_chips.get(part_type)
    if chip is None:
        raise DiagramError(f"custom chip part {part_type!r} has no task custom_chips entry")
    case_dir = diagram_path.parent
    wokwi_toml = case_dir / "wokwi.toml"
    if not wokwi_toml.exists():
        raise DiagramError(f"custom chip part {part_type!r} requires wokwi.toml")
    text = wokwi_toml.read_text(encoding="utf-8")
    name = str(chip["name"])
    binary = str(chip["binary"]).replace("\\", "/")
    if not re.search(r"\[\[chip\]\][\s\S]*?name\s*=\s*['\"]" + re.escape(name) + r"['\"]", text):
        raise DiagramError(f"custom chip {name!r} is missing [[chip]] name in wokwi.toml")
    if not re.search(r"\[\[chip\]\][\s\S]*?binary\s*=\s*['\"]" + re.escape(binary) + r"['\"]", text):
        raise DiagramError(f"custom chip {name!r} is missing binary path in wokwi.toml")
    binary_path = case_dir / binary
    json_path = binary_path.with_suffix(".json")
    if not binary_path.exists():
        raise DiagramError(f"custom chip binary not found: {binary_path}")
    if not json_path.exists():
        raise DiagramError(f"custom chip JSON not found: {json_path}")


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

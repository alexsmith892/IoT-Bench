"""Renode simulator backend: .repl/.resc emission and Zephyr west builds.

The Renode backend reuses the simulator-agnostic task schema: fixtures and
scenarios come from the same YAML families as Wokwi, validators consume the
same serial-log and VCD artifact shapes. The pieces that differ are isolated
here:

- ``generate_repl``: platform description (nRF52840 + probe LEDs on observed
  GPIO pins + button drivers for scenario inputs) instead of diagram.json.
- ``generate_resc``: a timed Renode monitor script that loads the firmware,
  captures UART to the serial log, synthesizes a Wokwi-shaped VCD from GPIO
  transitions via an embedded IronPython hook, and replays the scenario as
  ``emulation RunFor``/``Press``/``Release`` steps in exact virtual time.
- ``build_zephyr_case``: west build staged to a space-free directory
  (Zephyr's kconfig.cmake cannot handle spaces in the application path).
- ``simulate_case_renode``: headless Renode invocation.

See docs/renode-spike.md for the live-verified findings these encode.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .config import TaskConfig

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from .runner import CasePaths


class RenodeConfigError(Exception):
    """Raised when a task cannot be expressed as a Renode fixture."""


# The Arduino Nano 33 BLE ships a SAM-BA bootloader; Zephyr links at the
# code partition and the Cortex-M vector table must point there.
NANO33BLE_VECTOR_TABLE_OFFSET = "0x10000"

# Renode peripheral types the scenario emitter may drive, and the controls
# each accepts. Mirrors PART_TYPE_CONTROLS for Wokwi diagrams; linted the
# same way (unknown part/control fails at lint time). Sensor controls keep
# the Wokwi vocabulary (accelX in g, rotationX in deg/s) and map onto the
# Renode model's settable decimal properties below.
RENODE_PERIPHERAL_CONTROLS: dict[str, set[str]] = {
    "button": {"pressed"},
    # Wokwi digital_pullup surrogate semantics: idle HIGH, pressed=1 drives
    # the pin LOW (an inverted Renode Button).
    "digital_pullup": {"pressed"},
    # Cross-point key of the 4x4 matrix keypad model
    # (bench/chips/keypad/MatrixKeypad.cs), same vocabulary as the Wokwi
    # matrix_key surrogate.
    "matrix_key": {"pressed"},
    # IoT-Bench HC-SR04 model (bench/chips/hcsr04/HCSR04.cs): same `distance`
    # (cm) control as the Wokwi native part; echo width is 58 us/cm.
    "hcsr04": {"distance"},
    "dht11": {"temperature", "humidity"},
    "ds18b20": {"temperature"},
    "lsm9ds1": {"accelX", "accelY", "accelZ", "rotationX", "rotationY", "rotationZ", "temperature"},
    "ds1307": {"initTime"},
    # Native Renode BME280 (Antmicro.Renode.Peripherals.I2C.BME280). Only the
    # temperature and humidity channels are exposed: both round-trip exactly
    # through the Bosch compensation math over the model's registers (verified
    # live, Renode v1.16.1). The model's Pressure property is deliberately NOT
    # mapped: its encoder is ~1056x off from the datasheet compensation
    # formulas (setting 101325 Pa yields ~1.069e8 Pa from firmware-side Bosch
    # math, with ~6.4 kPa of quantization per ADC count), so no pressure
    # oracle over this model can be sound.
    "bme280": {"temperatureC", "humidityRH"},
    "bme280_spi": {"temperatureC", "humidityRH"},
    # IoT-Bench C# MPU6050 (bench/chips/mpu6050/MPU6050.cs): same control
    # vocabulary as the Wokwi-native MPU6050 (accel in g, rotation in deg/s).
    "mpu6050": {"accelX", "accelY", "accelZ", "rotationX", "rotationY", "rotationZ", "temperature"},
    # Analog voltage source on a SAADC channel (the Renode counterpart of the
    # Wokwi potentiometer surrogate): `position` is the Wokwi control
    # vocabulary (0..1 of full scale), `value` the raw ADC count attr.
    "analog_source": {"position", "value"},
}

# control name -> Renode model property for property-backed parts.
SENSOR_CONTROL_PROPERTIES: dict[str, dict[str, str]] = {
    "lsm9ds1": {
        "accelX": "AccelerationX",
        "accelY": "AccelerationY",
        "accelZ": "AccelerationZ",
        "rotationX": "AngularRateX",
        "rotationY": "AngularRateY",
        "rotationZ": "AngularRateZ",
        "temperature": "Temperature",
    },
    "ds1307": {
        "initTime": "InitTime",
    },
    "bme280": {
        "temperatureC": "Temperature",
        "humidityRH": "Humidity",
    },
    "bme280_spi": {
        "temperatureC": "Temperature",
        "humidityRH": "Humidity",
    },
    "mpu6050": {
        "accelX": "AccelerationX",
        "accelY": "AccelerationY",
        "accelZ": "AccelerationZ",
        "rotationX": "AngularRateX",
        "rotationY": "AngularRateY",
        "rotationZ": "AngularRateZ",
        "temperature": "Temperature",
    },
    "hcsr04": {
        "distance": "DistanceCm",
    },
    "dht11": {
        "temperature": "Temperature",
        "humidity": "Humidity",
    },
    "ds18b20": {
        "temperature": "Temperature",
    },
}

# Renode peripheral class per sensor part type, and which controls take a
# quoted string value instead of a bare decimal.
SENSOR_PART_CLASSES: dict[str, str] = {
    "lsm9ds1": "Sensors.LSM9DS1_IMU",
    "ds1307": "I2C.IoTBench_DS1307",
    "bme280": "I2C.BME280",
    "bme280_spi": "SPI.IoTBench_BME280_SPI",
    "mpu6050": "I2C.IoTBench_MPU6050",
}
STRING_VALUED_CONTROLS: dict[str, set[str]] = {
    "ds1307": {"initTime"},
}
# Sensor part types whose model is an IoT-Bench C# plugin compiled by Renode
# at include time, mapped to the source file under bench/chips/.
SENSOR_PLUGIN_SOURCES: dict[str, str] = {
    "ds1307": "ds1307/DS1307.cs",
    "mpu6050": "mpu6050/MPU6050.cs",
    "analog_source": "saadc/NRF52840_SAADC.cs",
    "matrix_key": "keypad/MatrixKeypad.cs",
    "hcsr04": "hcsr04/HCSR04.cs",
    "dht11": "dht11/DHT11.cs",
    "ds18b20": "ds18b20/DS18B20.cs",
    "bme280_spi": "bme280/BME280_SPI.cs",
}
DEFAULT_I2C_ADDRESSES: dict[str, int] = {
    "lsm9ds1": 0x6B,
    "ds1307": 0x68,
    "bme280": 0x76,
    "mpu6050": 0x68,
}

# Analog parts are not bus peripherals: they are channels of a single custom
# SAADC model mapped at the nRF52840 SAADC base address (the stock
# nrf52840.repl has nothing at 0x40007000 - verified live). All analog parts
# in a fixture share this one peripheral.
SAADC_MONITOR_NAME = "saadc0"
SAADC_REPL_CLASS = "Analog.IoTBench_NRF52840_SAADC"
SAADC_BASE_ADDRESS = "0x40007000"
SAADC_IRQ = 7

# All matrix_key parts in a fixture are cross-points of a single 4x4 keypad
# model, sysbus-mapped at an unused address purely for a monitor name; rows
# and columns are wired through GPIO connections in the generated repl.
KEYPAD_MONITOR_NAME = "keypad0"
KEYPAD_REPL_CLASS = "Miscellaneous.IoTBench_MatrixKeypad"
KEYPAD_BASE_ADDRESS = "0x5F000000"

# HC-SR04 models are sysbus-mapped at consecutive unused addresses (one per
# part, monitor name = part id); echo drives the configured pin, trigger is
# wired from its port into GPIO input 0.
HCSR04_REPL_CLASS = "Miscellaneous.IoTBench_HCSR04"
HCSR04_BASE_ADDRESS = 0x5F001000

# Single-wire GPIO sensor models are sysbus-mapped only to provide a monitor
# name for .resc property updates. Their data line is connected
# bidirectionally through GPIO.
DHT11_REPL_CLASS = "Miscellaneous.IoTBench_DHT11"
DS18B20_REPL_CLASS = "Miscellaneous.IoTBench_DS18B20"
ONEWIRE_BASE_ADDRESS = 0x5F020000

# Peripheral names already declared by platforms/cpus/nrf52840.repl; a part
# id reusing one fails at repl load with "Variable already declared".
RESERVED_PART_IDS = {
    "cpu", "nvic", "clock", "flash", "ram", "ppi", "gpiote",
    "gpio0", "gpio1", "uart0", "uart1", "twi0", "twi1", "spi2",
    "rtc0", "rtc1", "rtc2", "timer0", "timer1", "timer2", "timer3", "timer4",
    "wdt", "rng", "radio", "ficr", "temperature", "ecb", "sysbus", "i2s",
    # Declared by the backend itself when the fixture has analog/matrix parts.
    "saadc0", "keypad0",
}


def parse_gpio_pin(pin: str) -> tuple[str, int]:
    """Parse "P0.24" / "P1.11" / bare "24" into (gpio port name, pin index)."""
    text = str(pin).strip()
    match = re.fullmatch(r"[Pp]([01])\.(\d{1,2})", text)
    if match:
        return f"gpio{match.group(1)}", int(match.group(2))
    if re.fullmatch(r"\d{1,2}", text):
        return "gpio0", int(text)
    raise RenodeConfigError(f"unsupported nRF52840 pin spec: {pin!r} (use P0.nn / P1.nn)")


def analyzer_channels(task: TaskConfig) -> list[dict[str, str]]:
    return list(task.fixture.get("analyzer", {}).get("channels", []))


def probe_name(signal: str) -> str:
    return f"probe_{signal.lower()}"


def renode_parts(task: TaskConfig) -> dict[str, dict[str, Any]]:
    """Input-driver parts (buttons) the fixture provides, keyed by part id.

    Probes for analyzer channels are handled separately; this maps the
    scenario-controllable inputs. Fixture families reuse the Wokwi component
    vocabulary where it is digital-input or analog-source shaped (analog
    sources are channels of the custom SAADC model); anything that needs a
    peripheral model the backend lacks is rejected here so it fails at
    lint/generate time rather than producing a silent IF.
    """

    parts: dict[str, dict[str, Any]] = {}
    pins = task.fixture.get("pins", {}) or {}
    family = task.fixture_family

    def require_usable_id(part_id: str) -> None:
        if part_id.lower() in RESERVED_PART_IDS:
            raise RenodeConfigError(
                f"{task.task_id}: part id {part_id!r} collides with a peripheral "
                "declared by the nRF52840 platform; pick another id"
            )

    def add_button(part_id: str, pin: str, part_type: str = "button") -> None:
        require_usable_id(part_id)
        port, index = parse_gpio_pin(pin)
        parts[part_id] = {"type": part_type, "port": port, "pin": index}

    analog_channels_used = 0

    def add_analog(part_id: str, component: dict[str, Any]) -> None:
        nonlocal analog_channels_used
        require_usable_id(part_id)
        channel = component.get("channel")
        if channel is None:
            channel = analog_channels_used
        channel = int(channel)
        analog_channels_used = max(analog_channels_used, channel + 1)
        if not 0 <= channel <= 7:
            raise RenodeConfigError(
                f"{task.task_id}: analog component {part_id!r} channel {channel} outside SAADC 0..7"
            )
        attrs = dict(component.get("attrs") or {})
        for control in attrs:
            require_known_control(task, "analog_source", part_id, control)
        parts[part_id] = {"type": "analog_source", "channel": channel, "attrs": attrs}

    if family == "button_serial":
        add_button("btn1", pins.get("button", task.board_profile.default_pins["button"]))
    elif family == "pir_serial":
        add_button("pir1", pins.get("pir", pins.get("button", task.board_profile.default_pins["pir"])))
    elif family == "composite":
        for component in task.fixture.get("components", []) or []:
            ctype = str(component.get("type", ""))
            part_id = str(component.get("id", ""))
            if ctype in {"button", "wokwi-pushbutton", "digital_pullup", "pir", "shock_sensor"}:
                pin = str(component.get("pin") or component.get("pins", {}).get("signal", ""))
                if not pin:
                    raise RenodeConfigError(
                        f"{task.task_id}: composite component {part_id!r} needs a pin"
                    )
                add_button(part_id, pin, "digital_pullup" if ctype == "digital_pullup" else "button")
            elif ctype == "matrix_key":
                require_usable_id(part_id)
                key_pins = component.get("pins") or {}
                row = key_pins.get("row")
                col = key_pins.get("col")
                if not row or not col:
                    raise RenodeConfigError(
                        f"{task.task_id}: matrix_key {part_id!r} needs pins.row and pins.col"
                    )
                parts[part_id] = {
                    "type": "matrix_key",
                    "row_pin": parse_gpio_pin(str(row)),
                    "col_pin": parse_gpio_pin(str(col)),
                }
            elif ctype in {"dht11", "ds18b20"}:
                require_usable_id(part_id)
                data_pin = (component.get("pins") or {}).get("data")
                if not data_pin:
                    raise RenodeConfigError(
                        f"{task.task_id}: {ctype} {part_id!r} needs pins.data"
                    )
                attrs = dict(component.get("attrs") or {})
                for control in attrs:
                    require_known_control(task, ctype, part_id, control)
                parts[part_id] = {
                    "type": ctype,
                    "data_pin": parse_gpio_pin(str(data_pin)),
                    "attrs": attrs,
                }
            elif ctype in SENSOR_PART_CLASSES:
                require_usable_id(part_id)
                default_address = DEFAULT_I2C_ADDRESSES.get(ctype, 0)
                address = int(str(component.get("address", default_address)), 0)
                attrs = dict(component.get("attrs") or {})
                for control in attrs:
                    require_known_control(task, ctype, part_id, control)
                bus = str(component.get("bus", "spi2" if ctype == "bme280_spi" else "twi0"))
                parts[part_id] = {
                    "type": ctype,
                    "bus": bus,
                    "address": address,
                    "attrs": attrs,
                }
            elif ctype == "hcsr04":
                require_usable_id(part_id)
                sonar_pins = component.get("pins") or {}
                trig = sonar_pins.get("trig")
                echo = sonar_pins.get("echo")
                if not trig or not echo:
                    raise RenodeConfigError(
                        f"{task.task_id}: hcsr04 {part_id!r} needs pins.trig and pins.echo"
                    )
                attrs = dict(component.get("attrs") or {})
                for control in attrs:
                    require_known_control(task, ctype, part_id, control)
                parts[part_id] = {
                    "type": "hcsr04",
                    "trig_pin": parse_gpio_pin(str(trig)),
                    "echo_pin": parse_gpio_pin(str(echo)),
                    "attrs": attrs,
                }
            elif ctype in {"analog_source", "photoresistor", "potentiometer", "water_level", "joystick_axis"}:
                # Analog voltage sources are channels of the shared SAADC
                # model regardless of the physical part they stand in for;
                # the task YAML states the volts/counts mapping it assumes.
                add_analog(part_id, component)
            elif ctype in {"led", "buzzer", "active_buzzer", "lcd1602", "relay"}:
                # Outputs are observed via analyzer probes, not parts; the
                # LCD1602 in particular is decoded from the synthesized VCD
                # (bench/lcd1602.py), so no peripheral model is needed.
                continue
            else:
                raise RenodeConfigError(
                    f"{task.task_id}: component type {ctype!r} is not supported by the Renode backend"
                )
    elif family == "analog_temperature_serial":
        # Mirrors bench.diagrams.analog_temperature_serial: one potentiometer
        # surrogate ("pot1") as the analog voltage source, here a channel of
        # the custom SAADC model. initial_value is a raw ADC count.
        initial = task.fixture.get("analog_source", {}).get("initial_value", 153)
        require_usable_id("pot1")
        parts["pot1"] = {
            "type": "analog_source",
            "channel": 0,
            "attrs": {"value": initial},
        }
    elif family in {"single_led_output", "dual_led_output", "button_to_buzzer"}:
        if family == "button_to_buzzer":
            add_button("btn1", pins.get("button", task.board_profile.default_pins["button"]))
    else:
        raise RenodeConfigError(
            f"{task.task_id}: fixture family {family!r} is not supported by the Renode backend"
        )
    return parts


def keypad_layout(
    parts: dict[str, dict[str, Any]],
) -> tuple[list[tuple[str, int]], list[tuple[str, int]], dict[str, tuple[int, int]]]:
    """Row/column index assignment for matrix_key parts.

    Rows and columns are indexed in order of first appearance in the fixture
    (deterministic: fixture YAML order), so the generated wiring and the
    PressKey coordinates always agree with the task prompt's pin listing.
    """

    rows: list[tuple[str, int]] = []
    cols: list[tuple[str, int]] = []
    placement: dict[str, tuple[int, int]] = {}
    for part_id, part in parts.items():
        if part["type"] != "matrix_key":
            continue
        if part["row_pin"] not in rows:
            rows.append(part["row_pin"])
        if part["col_pin"] not in cols:
            cols.append(part["col_pin"])
        placement[part_id] = (rows.index(part["row_pin"]), cols.index(part["col_pin"]))
    if len(rows) > 4 or len(cols) > 4:
        raise RenodeConfigError(
            f"matrix keypad supports at most 4 rows and 4 columns (got {len(rows)}x{len(cols)})"
        )
    return rows, cols, placement


def require_known_control(task: TaskConfig, part_type: str, part_id: str, control: str) -> None:
    allowed = RENODE_PERIPHERAL_CONTROLS.get(part_type, set())
    if control not in allowed:
        raise RenodeConfigError(
            f"{task.task_id}: control {control!r} is not supported for {part_type} part "
            f"{part_id!r} (allowed: {sorted(allowed)})"
        )


def part_monitor_name(part: dict[str, Any], part_id: str) -> str:
    if part["type"] == "analog_source":
        # Analog parts are channels of the shared SAADC peripheral, which is
        # sysbus-mapped (monitor name is not parent-qualified under sysbus).
        return SAADC_MONITOR_NAME
    if part["type"] == "matrix_key":
        # Matrix keys are cross-points of the shared keypad peripheral.
        return KEYPAD_MONITOR_NAME
    if part["type"] == "hcsr04":
        # Sysbus-mapped under the part's own id (monitor name unqualified).
        return part_id
    if part["type"] in {"dht11", "ds18b20"}:
        return part_id
    if "bus" in part:
        return f"{part['bus']}.{part_id}"
    return f"{part['port']}.{part_id}"


def analog_raw_count(task: TaskConfig, part_id: str, control: str, value: Any) -> int:
    """Wokwi-vocabulary analog control -> raw ADC count.

    `position` is 0..1 of full scale (potentiometer control), `value` a raw
    count directly (the diagram attr). Out-of-range values fail at lint time.
    """

    adc_max = int(task.board_profile.adc_max)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RenodeConfigError(
            f"{task.task_id}: control {control!r} on {part_id!r} needs a numeric value, got {value!r}"
        ) from None
    raw = round(number * adc_max) if control == "position" else round(number)
    if not 0 <= raw <= adc_max:
        raise RenodeConfigError(
            f"{task.task_id}: control {control!r} value {value!r} on {part_id!r} "
            f"maps to raw count {raw}, outside 0..{adc_max}"
        )
    return raw


def control_set_command(
    task: TaskConfig, part_id: str, part: dict[str, Any], control: str, value: Any
) -> str:
    """One monitor command applying a control value to a part."""

    require_known_control(task, part["type"], part_id, control)
    if part["type"] in {"button", "digital_pullup"} and control == "pressed":
        # Press/Release semantics follow the part's polarity declared in the
        # repl (a digital_pullup is an inverted Button: Press drives LOW).
        return f"{part_monitor_name(part, part_id)} {'Press' if truthy_control(value) else 'Release'}"
    if part["type"] == "matrix_key" and control == "pressed":
        _, _, placement = keypad_layout(renode_parts(task))
        row, col = placement[part_id]
        verb = "PressKey" if truthy_control(value) else "ReleaseKey"
        return f"{KEYPAD_MONITOR_NAME} {verb} {row} {col}"
    if part["type"] == "analog_source":
        raw = analog_raw_count(task, part_id, control, value)
        channel = int(part.get("channel", 0))
        return f"{SAADC_MONITOR_NAME} Channel{channel}Value {raw}"
    prop = SENSOR_CONTROL_PROPERTIES[part["type"]][control]
    if control in STRING_VALUED_CONTROLS.get(part["type"], set()):
        return f'{part_monitor_name(part, part_id)} {prop} "{value}"'
    return f"{part_monitor_name(part, part_id)} {prop} {float(value):g}"


def sensor_plugin_files(task: TaskConfig) -> list[Path]:
    """C# plugin sources the case needs, included before the platform load."""

    bench_dir = Path(__file__).resolve().parent
    files = []
    for part in renode_parts(task).values():
        source = SENSOR_PLUGIN_SOURCES.get(part["type"])
        if source:
            path = bench_dir / "chips" / source
            if path not in files:
                files.append(path)
    return files


def part_attr_commands(task: TaskConfig, variant_attrs: dict[str, Any] | None = None) -> list[str]:
    """Property-set commands for fixture component attrs, overridden by the
    active variant's attrs (the Renode counterpart of Wokwi variant diagram
    attr patching; hashed via the per-variant resc)."""

    parts = renode_parts(task)
    merged: dict[str, dict[str, Any]] = {
        part_id: dict(part.get("attrs") or {}) for part_id, part in parts.items()
    }
    for part_id, attrs in (variant_attrs or {}).items():
        if part_id not in parts:
            raise RenodeConfigError(
                f"{task.task_id}: variant attrs reference unknown part {part_id!r}; "
                f"fixture provides {sorted(parts)}"
            )
        if not isinstance(attrs, dict):
            raise RenodeConfigError(f"{task.task_id}: variant attrs for {part_id!r} must be a mapping")
        merged.setdefault(part_id, {}).update(attrs)
    commands = []
    for part_id in sorted(merged):
        for control in sorted(merged[part_id]):
            commands.append(
                control_set_command(task, part_id, parts[part_id], control, merged[part_id][control])
            )
    return commands


def active_variant_attrs(task: TaskConfig) -> dict[str, Any] | None:
    variant = task.data.get("active_simulation_variant")
    if isinstance(variant, dict):
        attrs = variant.get("attrs")
        if isinstance(attrs, dict):
            return attrs
    return None


DEFAULT_PERFORMANCE_MIPS = 2


def performance_mips(task: TaskConfig) -> int:
    """CPU rating for the generated platform.

    Defaults to ``DEFAULT_PERFORMANCE_MIPS`` (tuned for busy-polling firmware).
    A task may opt into a higher rating via ``simulation.performance_mips`` when
    its firmware needs finer ``k_busy_wait``/``k_cycle_get_32`` resolution to
    bit-bang a microsecond single-wire protocol.
    """

    raw = task.simulation.get("performance_mips", DEFAULT_PERFORMANCE_MIPS)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise RenodeConfigError(
            f"{task.task_id}: simulation.performance_mips must be a positive integer, got {raw!r}"
        )
    if value <= 0:
        raise RenodeConfigError(
            f"{task.task_id}: simulation.performance_mips must be a positive integer, got {raw!r}"
        )
    return value


def generate_repl(task: TaskConfig) -> str:
    """Platform description for the case: nRF52840 + probes + input drivers."""

    lines = [
        "// Generated by bench.renode - do not edit by hand.",
        'using "platforms/cpus/nrf52840.repl"',
        "",
        "// Zephyr's arduino_nano_33_ble board config uses the legacy",
        "// nordic,nrf-uart driver; the stock model defaults to UARTE mode and",
        "// would drop all TX bytes (verified live, docs/renode-spike.md).",
        "uart0:",
        "    easyDMA: false",
        "",
        "// Busy-polling firmware (k_uptime_get loops) crosses the tlib/C#",
        "// boundary on every RTC read; at the default MIPS rating a 6 s run",
        "// takes >400 s wall (135 s at 10 MIPS). 2 MIPS keeps polling loops at",
        "// ~100 us resolution and Zephyr boot under 3 ms of virtual time while",
        "// making busy-polling firmware simulate fast enough to run.",
        "// Sleep-based firmware is unaffected (idle time is skipped either way).",
        "// Tasks whose firmware bit-bangs a microsecond single-wire protocol in a",
        "// short burst (DHT11, DS18B20) opt into a higher rating via the task's",
        "// simulation.performance_mips so k_busy_wait/k_cycle_get_32 resolve the",
        "// bit timing; the brief transactions keep the higher rating affordable.",
        "cpu:",
        f"    PerformanceInMips: {performance_mips(task)}",
        "",
    ]
    seen_pins: dict[tuple[str, int], str] = {}
    probes_by_port: dict[str, list[tuple[int, str]]] = {}
    for channel in analyzer_channels(task):
        signal = str(channel["signal"])
        port, index = parse_gpio_pin(str(channel["pin"]))
        name = probe_name(signal)
        if (port, index) in seen_pins:
            raise RenodeConfigError(
                f"{task.task_id}: analyzer channels {seen_pins[(port, index)]!r} and {name!r} share pin {port} {index}"
            )
        lines.append(f"{name}: Miscellaneous.LED @ {port} {index}")
        lines.append("")
        seen_pins[(port, index)] = name
        probes_by_port.setdefault(port, []).append((index, name))
    # Registering an LED at a GPIO pin does not wire the pin's output to it;
    # the port must also declare the connection (same as the stock board repl).
    for port in sorted(probes_by_port):
        lines.append(f"{port}:")
        for index, name in sorted(probes_by_port[port]):
            lines.append(f"    {index} -> {name}@0")
        lines.append("")
    saadc_declared = False
    parts = renode_parts(task)
    matrix_parts = {pid: p for pid, p in parts.items() if p["type"] == "matrix_key"}
    if matrix_parts:
        rows, cols, _ = keypad_layout(parts)
        for kind, pin_list in (("row", rows), ("column", cols)):
            for port, index in pin_list:
                if (port, index) in seen_pins:
                    raise RenodeConfigError(
                        f"{task.task_id}: keypad {kind} pin {port} {index} collides with probe "
                        f"{seen_pins[(port, index)]!r}"
                    )
        # One keypad peripheral; columns drive the column pins, row levels
        # are wired into the keypad's numbered inputs below.
        lines.append(f"{KEYPAD_MONITOR_NAME}: {KEYPAD_REPL_CLASS} @ sysbus {KEYPAD_BASE_ADDRESS}")
        for col_index, (port, index) in enumerate(cols):
            lines.append(f"    {col_index} -> {port}@{index}")
        lines.append("")
        rows_by_port: dict[str, list[tuple[int, int]]] = {}
        for row_index, (port, index) in enumerate(rows):
            rows_by_port.setdefault(port, []).append((index, row_index))
        for port in sorted(rows_by_port):
            lines.append(f"{port}:")
            for index, row_index in sorted(rows_by_port[port]):
                lines.append(f"    {index} -> {KEYPAD_MONITOR_NAME}@{row_index}")
            lines.append("")
    hcsr04_index = 0
    onewire_index = 0
    for part_id, part in parts.items():
        if part["type"] == "matrix_key":
            continue
        if part["type"] == "hcsr04":
            trig_port, trig_index = part["trig_pin"]
            echo_port, echo_index = part["echo_pin"]
            for kind, port, index in (("trig", trig_port, trig_index), ("echo", echo_port, echo_index)):
                if (port, index) in seen_pins:
                    raise RenodeConfigError(
                        f"{task.task_id}: hcsr04 {part_id!r} {kind} pin {port} {index} collides "
                        f"with probe {seen_pins[(port, index)]!r}"
                    )
            address = HCSR04_BASE_ADDRESS + hcsr04_index * 0x1000
            hcsr04_index += 1
            lines.append(f"{part_id}: {HCSR04_REPL_CLASS} @ sysbus {address:#x}")
            lines.append(f"    Echo -> {echo_port}@{echo_index}")
            lines.append("")
            lines.append(f"{trig_port}:")
            lines.append(f"    {trig_index} -> {part_id}@0")
            lines.append("")
            continue
        if part["type"] in {"dht11", "ds18b20"}:
            data_port, data_index = part["data_pin"]
            if (data_port, data_index) in seen_pins:
                raise RenodeConfigError(
                    f"{task.task_id}: {part['type']} {part_id!r} data pin {data_port} {data_index} "
                    f"collides with probe {seen_pins[(data_port, data_index)]!r}"
                )
            address = ONEWIRE_BASE_ADDRESS + onewire_index * 0x1000
            onewire_index += 1
            repl_class = DHT11_REPL_CLASS if part["type"] == "dht11" else DS18B20_REPL_CLASS
            lines.append(f"{part_id}: {repl_class} @ sysbus {address:#x}")
            lines.append(f"    Data -> {data_port}@{data_index}")
            lines.append("")
            lines.append(f"{data_port}:")
            lines.append(f"    {data_index} -> {part_id}@0")
            lines.append("")
            continue
        if part["type"] in {"button", "digital_pullup"}:
            port, index = part["port"], part["pin"]
            if (port, index) in seen_pins:
                raise RenodeConfigError(
                    f"{task.task_id}: part {part_id!r} and probe {seen_pins[(port, index)]!r} share pin {port} {index}"
                )
            lines.append(f"{part_id}: Miscellaneous.Button @ {port} {index}")
            if part["type"] == "digital_pullup":
                # Wokwi digital_pullup semantics: idle HIGH, Press drives LOW.
                lines.append("    invert: true")
            lines.append(f"    -> {port}@{index}")
            lines.append("")
        elif part["type"] == "analog_source":
            # All analog parts are channels of one SAADC instance; declare it
            # once. The model source is included by the generated .resc.
            if not saadc_declared:
                lines.append(
                    f"{SAADC_MONITOR_NAME}: {SAADC_REPL_CLASS} @ sysbus {SAADC_BASE_ADDRESS}"
                )
                lines.append(f"    -> nvic@{SAADC_IRQ}")
                lines.append("")
                saadc_declared = True
        else:
            if part["type"] == "bme280_spi":
                lines.append(f"{part_id}: {SENSOR_PART_CLASSES[part['type']]} @ {part['bus']}")
            else:
                lines.append(
                    f"{part_id}: {SENSOR_PART_CLASSES[part['type']]} @ {part['bus']} {part['address']:#x}"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def scenario_steps_to_resc(task: TaskConfig, scenario: dict[str, Any] | None) -> tuple[list[str], float]:
    """Convert generated scenario steps into timed monitor commands.

    Returns (commands, elapsed_virtual_seconds). Delays become
    ``emulation RunFor`` in exact virtual time; set-control steps become
    peripheral commands on the parts declared by the fixture.
    """

    if not scenario:
        return [], 0.0
    parts = renode_parts(task)
    commands: list[str] = []
    elapsed_s = 0.0
    pending_delay_ms = 0.0
    for step in scenario.get("steps", []):
        if "delay" in step:
            pending_delay_ms += parse_delay_ms(step["delay"])
            continue
        control = step.get("set-control")
        if control is None:
            raise RenodeConfigError(f"{task.task_id}: unsupported scenario step: {step}")
        if pending_delay_ms > 0:
            commands.append(run_for_command(pending_delay_ms))
            elapsed_s += pending_delay_ms / 1000.0
            pending_delay_ms = 0.0
        part_id = str(control["part-id"])
        name = str(control["control"])
        value = control["value"]
        part = parts.get(part_id)
        if part is None:
            raise RenodeConfigError(
                f"{task.task_id}: scenario drives unknown part {part_id!r}; fixture provides {sorted(parts)}"
            )
        # Peripherals registered on a bus/port are addressed through it
        # (sysbus.gpio1.btn1, sysbus.twi0.imu1); bare part ids are not
        # monitor names.
        commands.append(control_set_command(task, part_id, part, name, value))
    if pending_delay_ms > 0:
        commands.append(run_for_command(pending_delay_ms))
        elapsed_s += pending_delay_ms / 1000.0
    return commands, elapsed_s


def truthy_control(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", ""}
    return bool(value)


def parse_delay_ms(text: str) -> float:
    match = re.fullmatch(r"([0-9.]+)ms", str(text).strip())
    if not match:
        raise RenodeConfigError(f"unsupported scenario delay: {text!r}")
    return float(match.group(1))


def run_for_command(duration_ms: float) -> str:
    return f'emulation RunFor "{duration_ms / 1000.0:.6f}"'


def vcd_hook_python(task: TaskConfig, vcd_abspath: str) -> str:
    """IronPython 2 monitor block: buffer GPIO transitions, write VCD on flush.

    Same-timestamp events are coalesced (last value wins) and same-value runs
    deduped, because pin configuration produces glitch pairs within one
    microsecond tick and bench/vcd.py requires strictly increasing
    timestamps. Exceptions in hooks abort the emulation, so the handlers stay
    minimal.
    """

    channels = analyzer_channels(task)
    probe_lines = []
    for index, channel in enumerate(channels):
        signal = str(channel["signal"])
        name = probe_name(signal)
        probe_lines.append(
            f'_iotbench_attach("{signal}", "sysbus.{parse_gpio_pin(str(channel["pin"]))[0]}.{name}", {index})'
        )
    probes = "\n".join(probe_lines)
    return f'''python """
machine = monitor.Machine
iotbench_events = {{}}
iotbench_symbols = {{}}

def _iotbench_attach(signal, path, index):
    probe = machine[path]
    iotbench_symbols[signal] = chr(33 + index)
    iotbench_events[signal] = [(0, 1 if probe.State else 0)]
    def _on_state(_probe, state, _signal=signal):
        t = machine.ElapsedVirtualTime.TimeElapsed
        iotbench_events[_signal].append((int(t.TotalMicroseconds), 1 if state else 0))
    probe.StateChanged += _on_state

{probes}

def iotbench_write_vcd():
    # Absolute path: Renode changes its process CWD to its install dir, so
    # IronPython open() must not use case-relative paths (monitor @paths do
    # resolve against the including script and stay relative).
    out = open(r"{vcd_abspath}", "w")
    out.write("$timescale 1 us $end\\n")
    for signal in sorted(iotbench_symbols):
        out.write("$var wire 1 %s %s $end\\n" % (iotbench_symbols[signal], signal))
    out.write("$enddefinitions $end\\n")
    merged = []
    for signal, events in iotbench_events.items():
        symbol = iotbench_symbols[signal]
        coalesced = []
        for ts, val in events:
            if coalesced and coalesced[-1][0] == ts:
                coalesced[-1] = (ts, val)
            else:
                coalesced.append((ts, val))
        last = None
        for ts, val in coalesced:
            if val == last:
                continue
            merged.append((ts, symbol, val))
            last = val
    merged.sort()
    current = None
    for ts, symbol, val in merged:
        if ts != current:
            out.write("#%d\\n" % ts)
            current = ts
        out.write("%d%s\\n" % (val, symbol))
    out.close()

globals()["iotbench_write_vcd"] = iotbench_write_vcd
"""'''


def renode_at_path(path: str) -> str:
    """Monitor @path token: spaces must be backslash-escaped (verified live;
    quoting is not accepted by the tokenizer)."""

    return "@" + str(path).replace(" ", "\\ ")


def generate_resc(
    task: TaskConfig,
    *,
    repl_relpath: str,
    elf_relpath: str,
    serial_abspath: str | None,
    vcd_abspath: str | None,
    scenario: dict[str, Any] | None,
    timeout_ms: int,
    variant_attrs: dict[str, Any] | None = None,
) -> str:
    """The full monitor script for one simulation run (paths relative to cwd)."""

    lines = ["# Generated by bench.renode - do not edit by hand."]
    for plugin in sensor_plugin_files(task):
        # IoT-Bench C# peripheral models, compiled by Renode at include time;
        # must precede the platform description that instantiates them.
        lines.append(f"include {renode_at_path(str(plugin))}")
    lines.extend(
        [
            "using sysbus",
            f'mach create "{task.case_id}"',
            f"machine LoadPlatformDescription @{repl_relpath}",
            "",
            f"sysbus LoadELF @{elf_relpath}",
            f"cpu VectorTableOffset {NANO33BLE_VECTOR_TABLE_OFFSET}",
            "",
        ]
    )
    attr_commands = part_attr_commands(task, variant_attrs)
    if attr_commands:
        lines.extend(attr_commands)
        lines.append("")
    if serial_abspath:
        # Write-paths must be absolute: Renode resolves read @paths against
        # the including script, but creates files relative to its own CWD
        # (the install dir) - verified live.
        lines.append(f"uart0 CreateFileBackend {renode_at_path(serial_abspath)}")
        lines.append("")
    if vcd_abspath:
        lines.append(vcd_hook_python(task, vcd_abspath))
        lines.append("")

    scenario_commands, elapsed_s = scenario_steps_to_resc(task, scenario)
    total_s = timeout_ms / 1000.0
    if elapsed_s - total_s > 1e-9:
        raise RenodeConfigError(
            f"{task.task_id}: scenario runs {elapsed_s:.3f}s but simulation timeout is {total_s:.3f}s"
        )
    lines.extend(scenario_commands)
    remaining_s = total_s - elapsed_s
    if remaining_s > 1e-9:
        lines.append(f'emulation RunFor "{remaining_s:.6f}"')
    lines.append("")
    if vcd_abspath:
        lines.append('python """')
        lines.append("iotbench_write_vcd()")
        lines.append('"""')
        lines.append("")
    lines.append("quit")
    return "\n".join(lines) + "\n"


def validate_renode_case(task: TaskConfig, repl_path: Path, resc_path: Path | None = None) -> None:
    """Lint: regenerate the repl and confirm scenario controls resolve.

    The generated files are deterministic functions of the task YAML, so the
    strongest offline check is regeneration + control resolution (mirrors the
    Wokwi diagram lint + scenario-control allowlist).
    """

    expected = generate_repl(task)
    if not repl_path.exists():
        raise RenodeConfigError(f"platform description not found: {repl_path}")
    actual = repl_path.read_text(encoding="utf-8")
    if actual != expected:
        raise RenodeConfigError(
            f"{repl_path} does not match the fixture defined by {task.path}; regenerate the case"
        )
    from .scenarios import generate_scenario

    scenario_steps_to_resc(task, generate_scenario(task))
    validate_variant_scenarios(task)
    if resc_path is not None and not resc_path.exists():
        raise RenodeConfigError(f"simulation script not found: {resc_path}")


def validate_variant_scenarios(task: TaskConfig) -> None:
    """Per-variant scenario overrides get the same control lint as the base
    scenario, and per-variant attrs must target known parts and controls
    (mirrors the Wokwi variant-attr-target lint)."""

    from copy import deepcopy

    from .scenarios import generate_scenario

    for variant in task.simulation_variants:
        attrs = variant.get("attrs")
        if attrs:
            part_attr_commands(task, attrs)
        scenario = variant.get("scenario")
        if isinstance(scenario, dict):
            data = deepcopy(task.data)
            data["scenario"] = deepcopy(scenario)
            proxy = TaskConfig(path=task.path, data=data)
            scenario_steps_to_resc(proxy, generate_scenario(proxy))


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------

RENODE_DEFAULT_LOCATIONS = (
    Path("C:/Program Files/Renode/renode.exe"),
    Path("C:/Program Files/Renode/Renode.exe"),
)
CMAKE_DEFAULT_LOCATIONS = (Path("C:/Program Files/CMake/bin"),)


def renode_executable(override: str | None = None) -> str:
    if override and override != "renode":
        return override
    found = shutil.which("renode")
    if found:
        return found
    env = os.environ.get("IOTBENCH_RENODE")
    if env:
        return env
    for candidate in RENODE_DEFAULT_LOCATIONS:
        if candidate.exists():
            return str(candidate)
    return "renode"


def zephyr_workspace() -> Path:
    env = os.environ.get("ZEPHYR_WORKSPACE")
    if env:
        return Path(env)
    return Path.home() / "zephyrproject"


def west_executable(override: str | None = None) -> str:
    if override and override != "west":
        return override
    env = os.environ.get("IOTBENCH_WEST")
    if env:
        return env
    venv_west = zephyr_workspace() / ".venv" / "Scripts" / "west.exe"
    if venv_west.exists():
        return str(venv_west)
    found = shutil.which("west")
    if found:
        return found
    return "west"


def zephyr_build_root() -> Path:
    env = os.environ.get("IOTBENCH_ZEPHYR_BUILD_ROOT")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".cache"
    return base / "iot-bench" / "zephyr-build"


def zephyr_build_env() -> dict[str, str]:
    """Subprocess env for west: cmake/ninja prepended to PATH if missing.

    Non-interactive shells on this setup do not have cmake or ninja on PATH
    (doctor reports them); west fails with "CMake is not installed" otherwise.
    """

    env = dict(os.environ)
    prepend: list[str] = []
    if not shutil.which("cmake"):
        for candidate in CMAKE_DEFAULT_LOCATIONS:
            if (candidate / "cmake.exe").exists():
                prepend.append(str(candidate))
                break
    if not shutil.which("ninja"):
        local = os.environ.get("LOCALAPPDATA")
        if local:
            packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
            if packages.exists():
                for candidate in sorted(packages.glob("Ninja-build.Ninja_*")):
                    if (candidate / "ninja.exe").exists():
                        prepend.append(str(candidate))
                        break
    if prepend:
        env["PATH"] = os.pathsep.join([*prepend, env.get("PATH", "")])
    return env


def zephyr_revision(workspace: Path | None = None) -> str | None:
    zephyr_dir = (workspace or zephyr_workspace()) / "zephyr"
    try:
        completed = subprocess.run(
            ["git", "-C", str(zephyr_dir), "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout.strip()
    return output if completed.returncode == 0 and output else None

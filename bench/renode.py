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
# same way (unknown part/control fails at lint time).
RENODE_PERIPHERAL_CONTROLS: dict[str, set[str]] = {
    "button": {"pressed"},
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
    vocabulary where it is digital-input shaped; anything that needs a
    peripheral model Renode lacks (ADC sources, etc.) is rejected here so it
    fails at lint/generate time rather than producing a silent IF.
    """

    parts: dict[str, dict[str, Any]] = {}
    pins = task.fixture.get("pins", {}) or {}
    family = task.fixture_family

    def add_button(part_id: str, pin: str) -> None:
        port, index = parse_gpio_pin(pin)
        parts[part_id] = {"type": "button", "port": port, "pin": index}

    if family == "button_serial":
        add_button("btn1", pins.get("button", task.board_profile.default_pins["button"]))
    elif family == "pir_serial":
        add_button("pir1", pins.get("pir", pins.get("button", task.board_profile.default_pins["pir"])))
    elif family == "composite":
        for component in task.fixture.get("components", []) or []:
            ctype = str(component.get("type", ""))
            part_id = str(component.get("id", ""))
            if ctype in {"button", "wokwi-pushbutton", "digital_pullup", "pir"}:
                pin = str(component.get("pin") or component.get("pins", {}).get("signal", ""))
                if not pin:
                    raise RenodeConfigError(
                        f"{task.task_id}: composite component {part_id!r} needs a pin"
                    )
                add_button(part_id, pin)
            elif ctype in {"led", "buzzer"}:
                continue  # outputs are observed via analyzer probes, not parts
            else:
                raise RenodeConfigError(
                    f"{task.task_id}: component type {ctype!r} is not supported by the Renode backend"
                )
    elif family in {"single_led_output", "dual_led_output", "button_to_buzzer"}:
        if family == "button_to_buzzer":
            add_button("btn1", pins.get("button", task.board_profile.default_pins["button"]))
    else:
        raise RenodeConfigError(
            f"{task.task_id}: fixture family {family!r} is not supported by the Renode backend"
        )
    return parts


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
        "cpu:",
        "    PerformanceInMips: 2",
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
    for part_id, part in renode_parts(task).items():
        port, index = part["port"], part["pin"]
        if (port, index) in seen_pins:
            raise RenodeConfigError(
                f"{task.task_id}: part {part_id!r} and probe {seen_pins[(port, index)]!r} share pin {port} {index}"
            )
        lines.append(f"{part_id}: Miscellaneous.Button @ {port} {index}")
        lines.append(f"    -> {port}@{index}")
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
        allowed = RENODE_PERIPHERAL_CONTROLS[part["type"]]
        if name not in allowed:
            raise RenodeConfigError(
                f"{task.task_id}: control {name!r} is not supported for {part['type']} parts (allowed: {sorted(allowed)})"
            )
        if part["type"] == "button" and name == "pressed":
            # Peripherals registered on a GPIO port are addressed through it
            # (sysbus.gpio1.btn1); the bare part id is not a monitor name.
            commands.append(
                f"{part['port']}.{part_id} {'Press' if truthy_control(value) else 'Release'}"
            )
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
) -> str:
    """The full monitor script for one simulation run (paths relative to cwd)."""

    lines = [
        "# Generated by bench.renode - do not edit by hand.",
        "using sysbus",
        f'mach create "{task.case_id}"',
        f"machine LoadPlatformDescription @{repl_relpath}",
        "",
        f"sysbus LoadELF @{elf_relpath}",
        f"cpu VectorTableOffset {NANO33BLE_VECTOR_TABLE_OFFSET}",
        "",
    ]
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
    scenario; per-variant attrs are rejected until the backend grows
    peripheral models whose state variants can seed."""

    from copy import deepcopy

    from .scenarios import generate_scenario

    for variant in task.simulation_variants:
        variant_label = str(variant.get("id") or "variant")
        if variant.get("attrs"):
            raise RenodeConfigError(
                f"{task.task_id}: variant {variant_label!r} uses attrs, which the "
                "Renode backend does not support yet; use a scenario override"
            )
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

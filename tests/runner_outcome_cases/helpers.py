from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

from bench.config import DEFAULT_FQBN, TaskConfig
from bench.results import RESULT_BC, RESULT_BF, RESULT_CF, RESULT_IF
from bench.runner import CasePaths


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TASK_FIXTURES = FIXTURES / "tasks"


def task_fixture(level: str, task_id: str, outcome: str) -> Path:
    return TASK_FIXTURES / level / task_id / outcome / f"{outcome}.ino"


def task_config(root: Path, family: str, validator: dict[str, Any], *, static_checks: dict[str, Any] | None = None) -> TaskConfig:
    return TaskConfig(
        path=root / f"{family}.yaml",
        data={
            "task_id": f"runner_outcome_{family}",
            "fixture": {"family": "composite"},
            "validator": validator,
            "static_checks": static_checks or {},
            "case": {"id": f"runner-outcome-{family}", "sketch_name": f"runner_outcome_{family}"},
        },
    )


def case_paths(
    root: Path,
    task: TaskConfig,
    *,
    sketch: Path | None = None,
    vcd: Path | None = None,
    serial_log: Path | None = None,
) -> CasePaths:
    return CasePaths(
        task_id=task.task_id,
        case_id=task.case_id,
        case_dir=root,
        sketch=sketch or root / "sketch",
        diagram=root / "diagram.json",
        wokwi_toml=root / "wokwi.toml",
        build_dir=root / "artifacts" / "build",
        fqbn=DEFAULT_FQBN,
        vcd=vcd,
        serial_log=serial_log,
    )


def write_sketch(root: Path, source: str) -> Path:
    sketch = root / "sketch"
    sketch.mkdir(parents=True, exist_ok=True)
    (sketch / "runner_outcome.ino").write_text(source, encoding="utf-8")
    return sketch


def write_serial(root: Path, text: str) -> Path:
    serial = root / "artifacts" / "serial" / "serial.log"
    serial.parent.mkdir(parents=True, exist_ok=True)
    serial.write_text(text, encoding="utf-8")
    return serial


def assert_payload_result(testcase: unittest.TestCase, payload: dict[str, Any], result: str) -> None:
    testcase.assertEqual(payload["result"], result, payload)
    testcase.assertIn("classification", payload)
    testcase.assertIn("failure_stage", payload)
    testcase.assertIn("failure_source", payload)
    if result == RESULT_BC:
        testcase.assertEqual(payload["classification"], "PASS", payload)
        testcase.assertIsNone(payload["failure_stage"], payload)
        testcase.assertIsNone(payload["failure_source"], payload)
    elif result == RESULT_BF:
        testcase.assertEqual(payload["classification"], "FAIL", payload)
        testcase.assertEqual(payload["failure_stage"], "behavior", payload)
        testcase.assertEqual(payload["failure_source"], "user_code", payload)
    elif result == RESULT_CF:
        testcase.assertEqual(payload["classification"], "COMPILE_FAIL", payload)
        testcase.assertEqual(payload["failure_stage"], "compile", payload)
        testcase.assertEqual(payload["failure_source"], "user_code", payload)
    elif result == RESULT_IF:
        testcase.assertIn(payload["classification"], {"SIM_INFRA_FAIL", "SIM_OUTPUT_FAIL"}, payload)
        testcase.assertNotEqual(payload["failure_source"], "user_code", payload)


def run_cli(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise AssertionError(f"command failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
    return json.loads(completed.stdout)


def write_digital_vcd(path: Path, events: list[tuple[float, int]], *, signal: str = "D0") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "$version synthetic runner outcome test $end",
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
    return path


def write_multi_vcd(path: Path, signals: dict[str, list[tuple[float, int]]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    symbols = ["!", "?", "#", "$", "%", "&"]
    events: dict[float, list[str]] = {}
    for symbol, (_signal, signal_events) in zip(symbols, signals.items()):
        for timestamp_s, value in signal_events:
            events.setdefault(round(timestamp_s, 9), []).append(f"{value}{symbol}")

    lines = [
        "$version synthetic multi-signal runner outcome test $end",
        "$timescale 1ns $end",
        "$scope module logic $end",
    ]
    lines.extend(f"$var wire 1 {symbol} {signal} $end" for symbol, signal in zip(symbols, signals))
    lines.extend(["$upscope $end", "$enddefinitions $end"])
    for timestamp_s in sorted(events):
        lines.append(f"#{round(timestamp_s * 1_000_000_000)}")
        lines.extend(events[timestamp_s])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def blink_events(half_period_s: float, *, cycles: int = 6, start_s: float = 0.1) -> list[tuple[float, int]]:
    events = [(0.0, 0), (start_s, 1)]
    timestamp = start_s
    value = 1
    for _ in range(cycles * 2):
        timestamp += half_period_s
        value = 1 - value
        events.append((timestamp, value))
    return events


def morse_sos_events(unit_s: float, *, dash_units: int = 3) -> list[tuple[float, int]]:
    high_units = [1, 1, 1, dash_units, dash_units, dash_units, 1, 1, 1]
    gap_units = [1, 1, 3, 1, 1, 3, 1, 1, 7]
    events: list[tuple[float, int]] = [(0.0, 0)]
    timestamp = 0.3
    for high, gap in zip(high_units, gap_units):
        events.append((timestamp, 1))
        timestamp += high * unit_s
        events.append((timestamp, 0))
        timestamp += gap * unit_s
    return events


def write_pwm_vcd(path: Path, duty_steps: list[float]) -> Path:
    events: list[tuple[float, int]] = []
    timestamp = 0.0
    pwm_period_s = 0.001
    step_s = 0.010

    def append_event(time_s: float, value: int) -> None:
        if events and abs(events[-1][0] - time_s) < 1e-15:
            events[-1] = (time_s, value)
            return
        if events and events[-1][1] == value:
            return
        events.append((time_s, value))

    append_event(0.0, 0)
    for duty in duty_steps:
        step_start = timestamp
        for cycle in range(10):
            cycle_start = step_start + cycle * pwm_period_s
            high_s = max(0.0, min(1.0, duty)) * pwm_period_s
            if high_s > 0:
                append_event(cycle_start, 1)
            if high_s < pwm_period_s:
                append_event(cycle_start + high_s, 0)
        timestamp += step_s
    append_event(timestamp + 0.020, 0)
    return write_digital_vcd(path, events)


def write_lcd_vcd(path: Path, text: str) -> Path:
    events: dict[float, list[str]] = {}
    symbols = {"D0": "!", "D1": '"', "D2": "#", "D3": "$", "D4": "%", "D5": "&"}
    current = {name: 0 for name in symbols}

    def set_signal(time_s: float, name: str, value: int) -> None:
        if current[name] == value:
            return
        current[name] = value
        events.setdefault(round(time_s, 9), []).append(f"{value}{symbols[name]}")

    def write_nibble(time_s: float, rs: int, nibble: int) -> float:
        set_signal(time_s, "D0", rs)
        for bit, name in enumerate(("D2", "D3", "D4", "D5")):
            set_signal(time_s, name, (nibble >> bit) & 1)
        set_signal(time_s + 0.000001, "D1", 1)
        set_signal(time_s + 0.000002, "D1", 0)
        return time_s + 0.000050

    def write_byte(time_s: float, rs: int, byte: int) -> float:
        return write_nibble(write_nibble(time_s, rs, byte >> 4), rs, byte & 0x0F)

    timestamp = 0.0001
    timestamp = write_byte(timestamp, 0, 0x80)
    for char in text:
        timestamp = write_byte(timestamp, 1, ord(char))

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "$version synthetic lcd runner outcome test $end",
        "$timescale 1ns $end",
        "$scope module logic $end",
    ]
    lines.extend(f"$var wire 1 {symbol} {name} $end" for name, symbol in symbols.items())
    lines.extend(["$upscope $end", "$enddefinitions $end", "#0"])
    lines.extend(f"0{symbol}" for symbol in symbols.values())
    for timestamp_s in sorted(events):
        lines.append(f"#{round(timestamp_s * 1_000_000_000)}")
        lines.extend(events[timestamp_s])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

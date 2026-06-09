#!/usr/bin/env python3
"""Validate the blink_led_no_delay Wokwi case and source constraints."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from wokwi_case_runner import (
    BuildSimulationError,
    CaseConfigError,
    WokwiCaseConfig,
    default_case_dir,
    prepare_vcd,
    resolve_runner_config,
)
from validator_result import (
    FAIL,
    PASS,
    SIM_INFRA_FAIL,
    SIM_OUTPUT_FAIL,
    emit_result,
)


DEFAULT_CASE_DIR = default_case_dir("blink-led-no-delay-wokwi-mega")
DEFAULT_SIMULATION_TIME_MS = 6000
MIN_VALID_CYCLES = 4
HALF_RANGE_S = (0.475, 0.525)
PERIOD_RANGE_S = (0.95, 1.05)
DUTY_RANGE = (0.45, 0.55)
TIMESCALE_TO_SECONDS = {"1s": 1.0, "1ms": 1e-3, "1us": 1e-6, "1ns": 1e-9}


@dataclass(frozen=True)
class Event:
    timestamp_s: float
    value: int


@dataclass(frozen=True)
class Segment:
    value: int
    duration_s: float


@dataclass
class Metrics:
    num_transitions: int = 0
    static_check_passed: bool = False
    high_durations_s: list[float] = field(default_factory=list)
    low_durations_s: list[float] = field(default_factory=list)
    periods_s: list[float] = field(default_factory=list)
    average_frequency_hz: float | None = None
    average_duty_cycle: float | None = None

    def to_json(self) -> dict:
        return {
            "num_transitions": self.num_transitions,
            "static_check_passed": self.static_check_passed,
            "high_durations_s": [round(value, 9) for value in self.high_durations_s],
            "low_durations_s": [round(value, 9) for value in self.low_durations_s],
            "periods_s": [round(value, 9) for value in self.periods_s],
            "average_frequency_hz": round(self.average_frequency_hz, 9)
            if self.average_frequency_hz is not None
            else None,
            "average_duty_cycle": round(self.average_duty_cycle, 9)
            if self.average_duty_cycle is not None
            else None,
        }


class HarnessError(Exception):
    pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate non-blocking 1 Hz LED blink.")
    parser.add_argument("sketch", nargs="?", type=Path)
    parser.add_argument("diagram", nargs="?", type=Path)
    parser.add_argument("vcd", nargs="?", type=Path)
    parser.add_argument(
        "--case",
        type=Path,
        help=(
            "Case directory containing case.json. "
            f"Defaults to {DEFAULT_CASE_DIR}."
        ),
    )
    parser.add_argument(
        "--use-existing-vcd",
        action="store_true",
        help="Debug mode: skip compile/simulation and validate the configured VCD.",
    )
    parser.add_argument(
        "--archived-vcd",
        type=Path,
        help=(
            "Validate an archived VCD instead of the configured current VCD. "
            "Use a path, archive filename, or 'latest'."
        ),
    )
    parser.add_argument(
        "--simulation-time-ms",
        type=int,
        default=DEFAULT_SIMULATION_TIME_MS,
        help="Wokwi simulation duration in milliseconds.",
    )
    parser.add_argument(
        "--arduino-cli",
        default="arduino-cli",
        help="arduino-cli executable name or path.",
    )
    parser.add_argument(
        "--wokwi-cli",
        default="wokwi-cli",
        help="wokwi-cli executable name or path.",
    )
    return parser.parse_args(argv)


def emit(
    classification: str,
    reason: str,
    metrics: Metrics | None = None,
    *,
    failure_stage: str | None = None,
) -> int:
    return emit_result(
        classification,
        reason,
        (metrics or Metrics()).to_json(),
        failure_stage=failure_stage,
    )


def validate_static_no_delay(sketch_path: Path) -> None:
    ino_files = [sketch_path] if sketch_path.is_file() else sorted(sketch_path.glob("*.ino"))
    if not ino_files:
        raise HarnessError(f"no .ino file found in {sketch_path}")
    source = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in ino_files)
    stripped = strip_comments_and_strings(source)
    if re.search(r"\bdelay\s*\(", stripped):
        raise HarnessError("source contains blocking delay() call")
    if re.search(r"\bdelayMicroseconds\s*\(", stripped):
        raise HarnessError("source contains blocking delayMicroseconds() call")


def strip_comments_and_strings(source: str) -> str:
    result: list[str] = []
    index = 0
    state = "code"
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""

        if state == "code":
            if char == "/" and nxt == "/":
                state = "line_comment"
                result.append(" ")
                index += 2
            elif char == "/" and nxt == "*":
                state = "block_comment"
                result.append(" ")
                index += 2
            elif char == '"':
                state = "string"
                result.append(" ")
                index += 1
            elif char == "'":
                state = "char"
                result.append(" ")
                index += 1
            else:
                result.append(char)
                index += 1
        elif state == "line_comment":
            if char == "\n":
                result.append("\n")
                state = "code"
            else:
                result.append(" ")
            index += 1
        elif state == "block_comment":
            if char == "*" and nxt == "/":
                result.append(" ")
                state = "code"
                index += 2
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
        elif state == "string":
            if char == "\\":
                result.append(" ")
                index += 2
            elif char == '"':
                result.append(" ")
                state = "code"
                index += 1
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
        elif state == "char":
            if char == "\\":
                result.append(" ")
                index += 2
            elif char == "'":
                result.append(" ")
                state = "code"
                index += 1
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
    return "".join(result)


def validate_diagram(diagram_path: Path, signal_name: str, expected_pin: str) -> None:
    with diagram_path.open("r", encoding="utf-8") as handle:
        diagram = json.load(handle)
    connections = diagram.get("connections", [])
    has_signal = False
    has_ground = False
    for connection in connections:
        if not isinstance(connection, list) or len(connection) < 2:
            continue
        endpoints = {connection[0], connection[1]}
        if any(endpoint.endswith(f":{signal_name}") for endpoint in endpoints) and any(
            endpoint.endswith(f":{expected_pin}") for endpoint in endpoints
        ):
            has_signal = True
        if any(endpoint.endswith(":GND") for endpoint in endpoints) and any(
            ":GND" in endpoint for endpoint in endpoints
        ):
            has_ground = True
    if not has_signal:
        raise HarnessError(
            f"diagram does not show logic analyzer {signal_name} wired to GPIO {expected_pin}"
        )
    if not has_ground:
        raise HarnessError("diagram does not show logic analyzer GND wired to board GND")


def parse_vcd(vcd_path: Path, signal_name: str) -> list[Event]:
    if not vcd_path.exists():
        raise FileNotFoundError(f"VCD not found: {vcd_path}")

    timescale_s: float | None = None
    symbol: str | None = None
    timestamp = 0
    events: list[Event] = []
    with vcd_path.open("r", encoding="utf-8", errors="replace") as handle:
        in_defs = True
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("$timescale"):
                timescale_s = parse_timescale(line)
            elif in_defs and line.startswith("$var"):
                parts = line.split()
                if len(parts) >= 5 and parts[4] == signal_name:
                    symbol = parts[3]
            elif line.startswith("$enddefinitions"):
                in_defs = False
            elif line.startswith("#"):
                timestamp = int(line[1:])
            elif symbol:
                value = parse_value(line, symbol)
                if value is None:
                    continue
                if value not in (0, 1):
                    raise HarnessError(f"{signal_name} contains non-binary values")
                if timescale_s is None:
                    raise HarnessError("VCD is missing $timescale")
                events.append(Event(timestamp * timescale_s, value))
    if symbol is None:
        raise HarnessError(f"{signal_name} is missing from VCD definitions")
    return dedupe(events)


def parse_timescale(line: str) -> float:
    match = re.search(r"\$timescale\s+(\d+)\s*(ns|us|ms|s)\s+\$end", line)
    if not match:
        raise HarnessError(f"unsupported timescale: {line}")
    key = f"{int(match.group(1))}{match.group(2)}"
    if key not in TIMESCALE_TO_SECONDS:
        raise HarnessError(f"unsupported timescale {key}")
    return TIMESCALE_TO_SECONDS[key]


def parse_value(line: str, symbol: str) -> int | None:
    if line.startswith(("0", "1", "x", "X", "z", "Z")) and line[1:] == symbol:
        if line[0].lower() in ("x", "z"):
            return -1
        return int(line[0])
    return None


def dedupe(events: Iterable[Event]) -> list[Event]:
    result: list[Event] = []
    for event in events:
        if result and result[-1].value == event.value:
            continue
        result.append(event)
    return result


def build_segments(events: list[Event]) -> list[Segment]:
    segments: list[Segment] = []
    for current, following in zip(events, events[1:]):
        duration = following.timestamp_s - current.timestamp_s
        if duration <= 0:
            raise HarnessError("VCD timestamps are not strictly increasing")
        segments.append(Segment(current.value, duration))
    return segments


def validate_behavior(events: list[Event]) -> tuple[str, str, Metrics]:
    metrics = Metrics(num_transitions=max(0, len(events) - 1), static_check_passed=True)
    if len(events) < 2:
        return FAIL, "D0 has too few events", metrics

    segments = build_segments(events)
    if len(segments) < (MIN_VALID_CYCLES * 2 + 1):
        return FAIL, f"too few transitions for {MIN_VALID_CYCLES} post-startup cycles", metrics

    steady_segments = segments[1:]
    cycles: list[tuple[float, float]] = []
    index = 0
    while index + 1 < len(steady_segments) and len(cycles) < MIN_VALID_CYCLES:
        first = steady_segments[index]
        second = steady_segments[index + 1]
        if first.value == second.value:
            return FAIL, "D0 does not alternate cleanly between LOW and HIGH", metrics
        high = first.duration_s if first.value == 1 else second.duration_s
        low = first.duration_s if first.value == 0 else second.duration_s
        cycles.append((high, low))
        index += 2

    if len(cycles) < MIN_VALID_CYCLES:
        return FAIL, f"only {len(cycles)} complete post-startup cycles were captured", metrics

    metrics.high_durations_s = [high for high, _low in cycles]
    metrics.low_durations_s = [low for _high, low in cycles]
    metrics.periods_s = [high + low for high, low in cycles]
    duty_cycles = [high / (high + low) for high, low in cycles]
    avg_period = sum(metrics.periods_s) / len(metrics.periods_s)
    metrics.average_frequency_hz = 1.0 / avg_period
    metrics.average_duty_cycle = sum(duty_cycles) / len(duty_cycles)

    for duration in metrics.high_durations_s:
        if not in_range(duration, HALF_RANGE_S):
            return FAIL, f"HIGH duration {duration:.6f}s is outside tolerance", metrics
    for duration in metrics.low_durations_s:
        if not in_range(duration, HALF_RANGE_S):
            return FAIL, f"LOW duration {duration:.6f}s is outside tolerance", metrics
    for period in metrics.periods_s:
        if not in_range(period, PERIOD_RANGE_S):
            return FAIL, f"period {period:.6f}s is outside tolerance", metrics
    for duty_cycle in duty_cycles:
        if not in_range(duty_cycle, DUTY_RANGE):
            return FAIL, f"duty cycle {duty_cycle:.3f} is outside tolerance", metrics

    return PASS, "D0 shows non-blocking 1 Hz blink within tolerance", metrics


def in_range(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def main(argv: list[str]) -> int:
    metrics = Metrics()
    try:
        args = parse_args(argv)
        config: WokwiCaseConfig = resolve_runner_config(args, DEFAULT_CASE_DIR)
        prepare_vcd(
            config,
            use_existing_vcd=args.use_existing_vcd or args.archived_vcd is not None,
            simulation_time_ms=args.simulation_time_ms,
            arduino_cli=args.arduino_cli,
            wokwi_cli=args.wokwi_cli,
        )
    except BuildSimulationError as exc:
        return emit(
            exc.classification,
            str(exc),
            metrics,
            failure_stage=exc.failure_stage,
        )
    except CaseConfigError as exc:
        return emit(SIM_INFRA_FAIL, str(exc), metrics)

    try:
        validate_static_no_delay(config.sketch)
        metrics.static_check_passed = True
    except HarnessError as exc:
        return emit(FAIL, str(exc), metrics)

    try:
        validate_diagram(config.diagram, config.signal_name, config.expected_pin)
    except (OSError, json.JSONDecodeError, HarnessError, ValueError) as exc:
        return emit(SIM_INFRA_FAIL, str(exc), metrics)

    try:
        events = parse_vcd(config.vcd, config.signal_name)
        classification, reason, metrics = validate_behavior(events)
        return emit(classification, reason, metrics)
    except FileNotFoundError as exc:
        return emit(SIM_OUTPUT_FAIL, str(exc), metrics)
    except (OSError, HarnessError, ValueError) as exc:
        return emit(SIM_OUTPUT_FAIL, str(exc), metrics)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

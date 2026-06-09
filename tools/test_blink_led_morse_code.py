#!/usr/bin/env python3
"""Validate the blink_led_morse_code Wokwi case."""

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


DEFAULT_CASE_DIR = default_case_dir("blink-led-morse-code-wokwi-mega")
DEFAULT_SIMULATION_TIME_MS = 8000
UNIT_S = 0.2
TOLERANCE = 0.05
EXPECTED_UNITS = [1, 1, 1, 3, 3, 3, 1, 1, 1]
EXPECTED_GAP_UNITS = [1, 1, 3, 1, 1, 3, 1, 1]
TIMESCALE_TO_SECONDS = {"1s": 1.0, "1ms": 1e-3, "1us": 1e-6, "1ns": 1e-9}


@dataclass(frozen=True)
class Event:
    timestamp_s: float
    value: int


@dataclass(frozen=True)
class Segment:
    start_s: float
    value: int
    duration_s: float


@dataclass
class Metrics:
    num_transitions: int = 0
    match_start_s: float | None = None
    unit_estimate_s: float | None = None
    high_durations_s: list[float] = field(default_factory=list)
    gap_durations_s: list[float] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "num_transitions": self.num_transitions,
            "match_start_s": round(self.match_start_s, 9)
            if self.match_start_s is not None
            else None,
            "unit_estimate_s": round(self.unit_estimate_s, 9)
            if self.unit_estimate_s is not None
            else None,
            "high_durations_s": [round(value, 9) for value in self.high_durations_s],
            "gap_durations_s": [round(value, 9) for value in self.gap_durations_s],
        }


class HarnessError(Exception):
    pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate SOS Morse LED behavior.")
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
        segments.append(Segment(current.timestamp_s, current.value, duration))
    return segments


def validate_behavior(events: list[Event]) -> tuple[str, str, Metrics]:
    metrics = Metrics(num_transitions=max(0, len(events) - 1))
    if len(events) < 18:
        return FAIL, "too few D0 transitions to contain SOS", metrics

    try:
        segments = build_segments(events)
    except HarnessError as exc:
        return FAIL, str(exc), metrics

    for start in range(0, len(segments) - 16):
        candidate = segments[start : start + 17]
        if candidate[0].value != 1:
            continue
        if any(segment.value != (1 if index % 2 == 0 else 0) for index, segment in enumerate(candidate)):
            continue

        highs = [candidate[index].duration_s for index in range(0, 17, 2)]
        gaps = [candidate[index].duration_s for index in range(1, 16, 2)]
        if matches_units(highs, EXPECTED_UNITS) and matches_units(gaps, EXPECTED_GAP_UNITS):
            metrics.match_start_s = candidate[0].start_s
            metrics.high_durations_s = highs
            metrics.gap_durations_s = gaps
            metrics.unit_estimate_s = estimate_unit(highs, gaps)
            return PASS, "found valid SOS Morse sequence on D0", metrics

    return FAIL, "no valid SOS Morse sequence found on D0", metrics


def matches_units(durations: list[float], expected_units: list[int]) -> bool:
    return all(
        abs(duration - expected * UNIT_S) <= expected * UNIT_S * TOLERANCE
        for duration, expected in zip(durations, expected_units)
    )


def estimate_unit(highs: list[float], gaps: list[float]) -> float:
    samples = [
        duration / units
        for duration, units in zip(highs, EXPECTED_UNITS)
    ] + [
        duration / units
        for duration, units in zip(gaps, EXPECTED_GAP_UNITS)
    ]
    return sum(samples) / len(samples)


def main(argv: list[str]) -> int:
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
        validate_diagram(config.diagram, config.signal_name, config.expected_pin)
        events = parse_vcd(config.vcd, config.signal_name)
    except BuildSimulationError as exc:
        return emit(
            exc.classification,
            str(exc),
            failure_stage=exc.failure_stage,
        )
    except FileNotFoundError as exc:
        return emit(SIM_OUTPUT_FAIL, str(exc))
    except CaseConfigError as exc:
        return emit(SIM_INFRA_FAIL, str(exc))
    except (OSError, json.JSONDecodeError, CaseConfigError, HarnessError, ValueError) as exc:
        return emit(SIM_OUTPUT_FAIL, str(exc))

    classification, reason, metrics = validate_behavior(events)
    return emit(classification, reason, metrics)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Validate the breathing_led PWM Wokwi case."""

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


DEFAULT_CASE_DIR = default_case_dir("breathing-led-wokwi-mega")
DEFAULT_SIMULATION_TIME_MS = 2000
STEP_INTERVAL_S = 0.010
STEP_RANGE_S = (0.009, 0.011)
BREATHING_PERIOD_RANGE_S = (0.95, 1.05)
DUTY_TOLERANCE = 0.03
LEVELS = 50
TIMESCALE_TO_SECONDS = {"1s": 1.0, "1ms": 1e-3, "1us": 1e-6, "1ns": 1e-9}


@dataclass(frozen=True)
class Event:
    timestamp_s: float
    value: int


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    value: int


@dataclass
class Metrics:
    num_transitions: int = 0
    match_start_s: float | None = None
    measured_duty_cycles: list[float] = field(default_factory=list)
    expected_duty_cycles: list[float] = field(default_factory=list)
    step_intervals_s: list[float] = field(default_factory=list)
    average_pwm_period_s: float | None = None
    breathing_period_s: float | None = None
    monotonicity_passed: bool = False

    def to_json(self) -> dict:
        return {
            "num_transitions": self.num_transitions,
            "match_start_s": round(self.match_start_s, 9)
            if self.match_start_s is not None
            else None,
            "measured_duty_cycles": [round(value, 5) for value in self.measured_duty_cycles],
            "expected_duty_cycles": [round(value, 5) for value in self.expected_duty_cycles],
            "step_intervals_s": [round(value, 9) for value in self.step_intervals_s],
            "average_pwm_period_s": round(self.average_pwm_period_s, 9)
            if self.average_pwm_period_s is not None
            else None,
            "breathing_period_s": round(self.breathing_period_s, 9)
            if self.breathing_period_s is not None
            else None,
            "monotonicity_passed": self.monotonicity_passed,
        }


class HarnessError(Exception):
    pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate PWM breathing LED behavior.")
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
        if following.timestamp_s <= current.timestamp_s:
            raise HarnessError("VCD timestamps are not strictly increasing")
        segments.append(Segment(current.timestamp_s, following.timestamp_s, current.value))
    return segments


def integrate_high_time(segments: list[Segment], start_s: float, end_s: float) -> float:
    high_time = 0.0
    for segment in segments:
        if segment.end_s <= start_s:
            continue
        if segment.start_s >= end_s:
            break
        if segment.value == 1:
            high_time += max(0.0, min(segment.end_s, end_s) - max(segment.start_s, start_s))
    return high_time


def expected_sequence() -> list[float]:
    rising = [(index + 1) / LEVELS for index in range(LEVELS)]
    return rising + list(reversed(rising))


def validate_behavior(events: list[Event]) -> tuple[str, str, Metrics]:
    metrics = Metrics(num_transitions=max(0, len(events) - 1))
    if len(events) < 100:
        return FAIL, "too few D0 transitions for PWM breathing analysis", metrics

    segments = build_segments(events)
    total_duration = events[-1].timestamp_s - events[0].timestamp_s
    if total_duration < BREATHING_PERIOD_RANGE_S[0]:
        return FAIL, "trace is too short to contain one breathing period", metrics

    expected = expected_sequence()
    best_metrics: Metrics | None = None
    best_score = 10**9
    last_start = events[-1].timestamp_s - STEP_INTERVAL_S * len(expected)
    if last_start <= events[0].timestamp_s:
        return FAIL, "trace is too short to measure 100 breathing steps", metrics

    # Try 1 ms alignments so the test does not require the breathing cycle to
    # begin exactly when the VCD starts.
    start = events[0].timestamp_s
    while start <= min(events[0].timestamp_s + 0.100, last_start):
        measured = [
            integrate_high_time(segments, start + i * STEP_INTERVAL_S, start + (i + 1) * STEP_INTERVAL_S)
            / STEP_INTERVAL_S
            for i in range(len(expected))
        ]
        score = sum(abs(actual - wanted) for actual, wanted in zip(measured, expected))
        if score < best_score:
            best_score = score
            best_metrics = Metrics(
                num_transitions=metrics.num_transitions,
                match_start_s=start,
                measured_duty_cycles=measured,
                expected_duty_cycles=expected,
                step_intervals_s=[STEP_INTERVAL_S for _ in range(len(expected) - 1)],
                average_pwm_period_s=average_pwm_period(events),
                breathing_period_s=STEP_INTERVAL_S * len(expected),
                monotonicity_passed=is_monotonic_breath(measured),
            )
        start += 0.001

    if best_metrics is None:
        return FAIL, "could not align breathing windows", metrics

    if any(not in_range(interval, STEP_RANGE_S) for interval in best_metrics.step_intervals_s):
        return FAIL, "duty step interval is outside tolerance", best_metrics
    if not in_range(best_metrics.breathing_period_s or 0.0, BREATHING_PERIOD_RANGE_S):
        return FAIL, "breathing period is outside tolerance", best_metrics
    if not best_metrics.monotonicity_passed:
        return FAIL, "duty cycle sequence is not monotonic rise then fall", best_metrics

    for actual, wanted in zip(best_metrics.measured_duty_cycles, best_metrics.expected_duty_cycles):
        if abs(actual - wanted) > DUTY_TOLERANCE:
            return (
                FAIL,
                f"duty cycle {actual:.3f} is outside tolerance for expected {wanted:.3f}",
                best_metrics,
            )

    return PASS, "D0 shows 50-level 1 Hz PWM breathing behavior within tolerance", best_metrics


def is_monotonic_breath(values: list[float]) -> bool:
    if len(values) < LEVELS * 2:
        return False
    rising = values[:LEVELS]
    falling = values[LEVELS:]
    return all(a <= b + DUTY_TOLERANCE for a, b in zip(rising, rising[1:])) and all(
        a + DUTY_TOLERANCE >= b for a, b in zip(falling, falling[1:])
    )


def average_pwm_period(events: list[Event]) -> float | None:
    rising_edges = [
        current.timestamp_s
        for previous, current in zip(events, events[1:])
        if previous.value == 0 and current.value == 1
    ]
    periods = [
        following - current
        for current, following in zip(rising_edges, rising_edges[1:])
        if following - current < 0.005
    ]
    if not periods:
        return None
    return sum(periods) / len(periods)


def in_range(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


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
        classification, reason, metrics = validate_behavior(events)
        return emit(classification, reason, metrics)
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
    except (OSError, json.JSONDecodeError, HarnessError, ValueError) as exc:
        return emit(SIM_OUTPUT_FAIL, str(exc))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

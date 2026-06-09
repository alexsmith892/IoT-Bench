#!/usr/bin/env python3
"""Automated Wokwi harness for the 1 Hz GPIO 3 LED blink task.

The harness intentionally does not inspect the submitted sketch for pin usage.
By default it compiles the case sketch, runs Wokwi headlessly, exports a fresh
logic-analyzer VCD, then validates the observed D0 waveform.
"""

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
    COMPILE_FAIL,
    FAIL,
    PASS,
    SIM_INFRA_FAIL,
    SIM_OUTPUT_FAIL,
    emit_result,
)


DEFAULT_CASE_DIR = default_case_dir("blink-1hz-wokwi-mega")
DEFAULT_SIMULATION_TIME_MS = 6000

MIN_VALID_CYCLES = 4
HALF_PERIOD_RANGE_S = (0.450, 0.550)
FULL_PERIOD_RANGE_S = (0.900, 1.100)
DUTY_CYCLE_RANGE = (0.40, 0.60)

TIMESCALE_TO_SECONDS = {
    "1s": 1.0,
    "1ms": 1e-3,
    "1us": 1e-6,
    "1ns": 1e-9,
}


@dataclass(frozen=True)
class VcdEvent:
    timestamp_s: float
    value: int


@dataclass(frozen=True)
class Segment:
    value: int
    duration_s: float


@dataclass
class Metrics:
    num_transitions: int = 0
    high_durations_s: list[float] = field(default_factory=list)
    low_durations_s: list[float] = field(default_factory=list)
    periods_s: list[float] = field(default_factory=list)
    average_period_s: float | None = None
    average_frequency_hz: float | None = None
    average_duty_cycle: float | None = None

    def to_json(self) -> dict:
        return {
            "num_transitions": self.num_transitions,
            "high_durations_s": [round(v, 9) for v in self.high_durations_s],
            "low_durations_s": [round(v, 9) for v in self.low_durations_s],
            "periods_s": [round(v, 9) for v in self.periods_s],
            "average_period_s": round(self.average_period_s, 9)
            if self.average_period_s is not None
            else None,
            "average_frequency_hz": round(self.average_frequency_hz, 9)
            if self.average_frequency_hz is not None
            else None,
            "average_duty_cycle": round(self.average_duty_cycle, 9)
            if self.average_duty_cycle is not None
            else None,
        }


@dataclass(frozen=True)
class Classification:
    classification: str
    reason: str
    metrics: Metrics = field(default_factory=Metrics)

    def to_json(self) -> dict:
        return {
            "classification": self.classification,
            "reason": self.reason,
            "metrics": self.metrics.to_json(),
        }


class HarnessError(Exception):
    """Base class for expected harness errors."""


class CompileOrSimulationError(HarnessError):
    """Raised when compile/flashing/simulation command execution fails."""


class VcdParseError(HarnessError):
    """Raised when the VCD cannot be parsed."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify a Wokwi Arduino GPIO 3 / D0 1 Hz blink submission."
    )
    parser.add_argument(
        "sketch",
        nargs="?",
        type=Path,
        help="Path to the submitted Arduino sketch file or sketch directory.",
    )
    parser.add_argument(
        "diagram",
        nargs="?",
        type=Path,
        help="Path to Wokwi diagram.json.",
    )
    parser.add_argument(
        "vcd",
        nargs="?",
        type=Path,
        help="Path to exported logic-analyzer VCD.",
    )
    parser.add_argument(
        "--case",
        type=Path,
        help=(
            "Path to a self-contained test case directory containing case.json. "
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
    parser.add_argument(
        "--skip-diagram-check",
        action="store_true",
        help="Skip validation that logic analyzer D0 is wired to GPIO 3.",
    )
    return parser.parse_args(argv)


def final_result(
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


def validate_diagram_wiring(
    diagram_path: Path,
    *,
    signal_name: str = "D0",
    expected_pin: str = "3",
) -> None:
    if not diagram_path.exists():
        raise VcdParseError(f"diagram.json not found: {diagram_path}")

    with diagram_path.open("r", encoding="utf-8") as handle:
        diagram = json.load(handle)

    connections = diagram.get("connections", [])
    has_d0_to_pin3 = False
    has_logic_gnd = False
    for connection in connections:
        if not isinstance(connection, list) or len(connection) < 2:
            continue
        a, b = connection[0], connection[1]
        endpoints = {a, b}
        if any(endpoint.endswith(f":{signal_name}") for endpoint in endpoints) and any(
            endpoint.endswith(f":{expected_pin}") for endpoint in endpoints
        ):
            has_d0_to_pin3 = True
        if any(endpoint.endswith(":GND") for endpoint in endpoints) and any(
            ":GND" in endpoint for endpoint in endpoints
        ):
            has_logic_gnd = True

    if not has_d0_to_pin3:
        raise VcdParseError(
            f"diagram does not show logic analyzer {signal_name} wired to GPIO {expected_pin}"
        )
    if not has_logic_gnd:
        raise VcdParseError("diagram does not show logic analyzer GND wired to board GND")


def parse_timescale(line: str) -> float:
    match = re.search(r"\$timescale\s+(\d+)\s*(ns|us|ms|s)\s+\$end", line)
    if not match:
        raise VcdParseError(f"unsupported or missing timescale line: {line.strip()}")

    magnitude = int(match.group(1))
    unit = match.group(2)
    key = f"{magnitude}{unit}"
    if key not in TIMESCALE_TO_SECONDS:
        raise VcdParseError(
            f"unsupported timescale {key}; supported: {', '.join(TIMESCALE_TO_SECONDS)}"
        )
    return TIMESCALE_TO_SECONDS[key]


def parse_vcd(vcd_path: Path, signal_name: str = "D0") -> list[VcdEvent]:
    if not vcd_path.exists():
        raise VcdParseError(f"VCD not found: {vcd_path}")

    timescale_s: float | None = None
    d0_symbol: str | None = None
    current_timestamp_ticks = 0
    events: list[VcdEvent] = []
    invalid_values: list[str] = []

    with vcd_path.open("r", encoding="utf-8", errors="replace") as handle:
        in_definitions = True
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("$timescale"):
                timescale_s = parse_timescale(line)
                continue

            if in_definitions and line.startswith("$var"):
                parts = line.split()
                if len(parts) >= 5 and parts[4] == signal_name:
                    d0_symbol = parts[3]
                continue

            if line.startswith("$enddefinitions"):
                in_definitions = False
                continue

            if line.startswith("#"):
                try:
                    current_timestamp_ticks = int(line[1:])
                except ValueError as exc:
                    raise VcdParseError(f"invalid VCD timestamp: {line}") from exc
                continue

            if d0_symbol is None:
                continue

            value = parse_scalar_value_for_symbol(line, d0_symbol)
            if value is None:
                continue
            if value not in (0, 1):
                invalid_values.append(str(value))
                continue
            if timescale_s is None:
                raise VcdParseError("VCD is missing $timescale before value changes")
            events.append(VcdEvent(current_timestamp_ticks * timescale_s, value))

    if d0_symbol is None:
        raise VcdParseError(f"{signal_name} is missing from VCD definitions")
    if invalid_values:
        raise VcdParseError(f"{signal_name} contains non-binary values")

    return dedupe_same_value_events(events)


def parse_scalar_value_for_symbol(line: str, symbol: str) -> int | None:
    if line.startswith(("0", "1", "x", "X", "z", "Z")):
        if line[1:] == symbol:
            value = line[0].lower()
            if value in ("x", "z"):
                return -1
            return int(value)
        return None

    if line.startswith(("b", "B")):
        parts = line.split()
        if len(parts) == 2 and parts[1] == symbol:
            bits = parts[0][1:].lower()
            if any(bit in bits for bit in ("x", "z")):
                return -1
            try:
                return int(bits, 2)
            except ValueError:
                return -1

    return None


def dedupe_same_value_events(events: Iterable[VcdEvent]) -> list[VcdEvent]:
    deduped: list[VcdEvent] = []
    for event in events:
        if deduped and deduped[-1].value == event.value:
            continue
        deduped.append(event)
    return deduped


def build_segments(events: list[VcdEvent]) -> list[Segment]:
    segments: list[Segment] = []
    for current, following in zip(events, events[1:]):
        duration = following.timestamp_s - current.timestamp_s
        if duration <= 0:
            raise VcdParseError("D0 timestamps are not strictly increasing")
        segments.append(Segment(current.value, duration))
    return segments


def validate_behavior(events: list[VcdEvent]) -> Classification:
    metrics = Metrics(num_transitions=max(0, len(events) - 1))

    if len(events) < 2:
        return Classification(FAIL, "D0 has too few events", metrics)

    for previous, current in zip(events, events[1:]):
        if previous.value == current.value:
            return Classification(
                FAIL,
                "D0 does not alternate cleanly between LOW and HIGH",
                metrics,
            )

    try:
        segments = build_segments(events)
    except VcdParseError as exc:
        return Classification(CLASS_BEHAVIOR_FAILURE, str(exc), metrics)

    if len(segments) < (MIN_VALID_CYCLES * 2 + 1):
        return Classification(
            FAIL,
            f"too few D0 transitions for {MIN_VALID_CYCLES} post-startup cycles",
            metrics,
        )

    # Ignore the first observed segment because startup can truncate the first
    # HIGH or LOW interval before steady-state blinking begins.
    steady_segments = segments[1:]
    cycles: list[tuple[float, float]] = []
    index = 0
    while index + 1 < len(steady_segments) and len(cycles) < MIN_VALID_CYCLES:
        first = steady_segments[index]
        second = steady_segments[index + 1]
        if first.value == second.value:
            return Classification(
                FAIL,
                "D0 does not alternate cleanly between LOW and HIGH",
                metrics,
            )
        high_duration = first.duration_s if first.value == 1 else second.duration_s
        low_duration = first.duration_s if first.value == 0 else second.duration_s
        cycles.append((high_duration, low_duration))
        index += 2

    if len(cycles) < MIN_VALID_CYCLES:
        return Classification(
            FAIL,
            f"only {len(cycles)} complete post-startup cycles were captured",
            metrics,
        )

    metrics.high_durations_s = [high for high, _low in cycles]
    metrics.low_durations_s = [low for _high, low in cycles]
    metrics.periods_s = [high + low for high, low in cycles]
    duty_cycles = [
        high / (high + low) for high, low in cycles if (high + low) > 0
    ]
    metrics.average_period_s = average(metrics.periods_s)
    metrics.average_frequency_hz = (
        1.0 / metrics.average_period_s if metrics.average_period_s else None
    )
    metrics.average_duty_cycle = average(duty_cycles)

    for duration in metrics.high_durations_s:
        if not in_range(duration, HALF_PERIOD_RANGE_S):
            return Classification(
                FAIL,
                f"HIGH duration {duration:.6f}s is outside tolerance",
                metrics,
            )
    for duration in metrics.low_durations_s:
        if not in_range(duration, HALF_PERIOD_RANGE_S):
            return Classification(
                FAIL,
                f"LOW duration {duration:.6f}s is outside tolerance",
                metrics,
            )
    for period in metrics.periods_s:
        if not in_range(period, FULL_PERIOD_RANGE_S):
            return Classification(
                FAIL,
                f"period {period:.6f}s is outside tolerance",
                metrics,
            )
    for duty_cycle in duty_cycles:
        if not in_range(duty_cycle, DUTY_CYCLE_RANGE):
            return Classification(
                FAIL,
                f"duty cycle {duty_cycle:.3f} is outside tolerance",
                metrics,
            )

    return Classification(
        PASS,
        f"D0 shows {MIN_VALID_CYCLES} valid 1 Hz cycles within tolerance",
        metrics,
    )


def in_range(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        config: WokwiCaseConfig = resolve_runner_config(args, DEFAULT_CASE_DIR)
        prepare_vcd(
            config,
            use_existing_vcd=args.use_existing_vcd or args.archived_vcd is not None,
            simulation_time_ms=args.simulation_time_ms,
            arduino_cli=args.arduino_cli,
            wokwi_cli=args.wokwi_cli,
        )
        if not args.skip_diagram_check:
            validate_diagram_wiring(
                config.diagram,
                signal_name=config.signal_name,
                expected_pin=config.expected_pin,
            )
    except BuildSimulationError as exc:
        return final_result(
            exc.classification,
            str(exc),
            failure_stage=exc.failure_stage,
        )
    except CompileOrSimulationError as exc:
        return final_result(COMPILE_FAIL, str(exc))
    except CaseConfigError as exc:
        return final_result(SIM_INFRA_FAIL, str(exc))
    except (OSError, json.JSONDecodeError, VcdParseError) as exc:
        return final_result(SIM_INFRA_FAIL, str(exc))

    try:
        events = parse_vcd(config.vcd, config.signal_name)
    except VcdParseError as exc:
        return final_result(SIM_OUTPUT_FAIL, str(exc))

    result = validate_behavior(events)
    return final_result(result.classification, result.reason, result.metrics)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

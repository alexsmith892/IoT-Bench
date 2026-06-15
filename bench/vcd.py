"""Small VCD parser and digital waveform analysis helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TIMESCALE_UNITS_TO_SECONDS = {
    "s": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "ns": 1e-9,
    "ps": 1e-12,
}


class VcdParseError(Exception):
    """Raised when a VCD cannot be parsed into binary signal events."""


@dataclass(frozen=True)
class VcdEvent:
    timestamp_s: float
    value: int


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    value: int

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def parse_timescale(line: str) -> float:
    match = re.search(r"\$timescale\s+(\d+)\s*(ps|ns|us|ms|s)\s+\$end", line)
    if not match:
        raise VcdParseError(f"unsupported or missing timescale line: {line.strip()}")
    return int(match.group(1)) * TIMESCALE_UNITS_TO_SECONDS[match.group(2)]


def parse_vcd_signal(vcd_path: Path, signal_name: str = "D0") -> list[VcdEvent]:
    return parse_vcd_signals(vcd_path, [signal_name])[signal_name]


def parse_vcd_signals(
    vcd_path: Path, signal_names: Iterable[str]
) -> dict[str, list[VcdEvent]]:
    if not vcd_path.exists():
        raise VcdParseError(f"VCD not found: {vcd_path}")
    if vcd_path.stat().st_size == 0:
        raise VcdParseError(f"VCD is empty: {vcd_path}")

    requested = list(signal_names)
    requested_set = set(requested)
    symbol_to_name: dict[str, str] = {}
    timescale_s: float | None = None
    timestamp_ticks = 0
    events = {name: [] for name in requested}
    invalid_values: dict[str, list[str]] = {name: [] for name in requested}

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
                if len(parts) >= 5 and parts[4] in requested_set:
                    symbol_to_name[parts[3]] = parts[4]
                continue

            if line.startswith("$enddefinitions"):
                in_definitions = False
                continue

            if line.startswith("#"):
                try:
                    timestamp_ticks = int(line[1:])
                except ValueError as exc:
                    raise VcdParseError(f"invalid VCD timestamp: {line}") from exc
                continue

            if not symbol_to_name:
                continue

            parsed = parse_scalar_value(line, symbol_to_name)
            if parsed is None:
                continue
            signal_name, value = parsed
            if value not in (0, 1):
                invalid_values[signal_name].append(str(value))
                continue
            if timescale_s is None:
                raise VcdParseError("VCD is missing $timescale before value changes")
            events[signal_name].append(VcdEvent(timestamp_ticks * timescale_s, value))

    missing = [name for name in requested if name not in set(symbol_to_name.values())]
    if missing:
        raise VcdParseError(f"missing VCD signal(s): {', '.join(missing)}")
    invalid = [name for name, values in invalid_values.items() if values]
    if invalid:
        raise VcdParseError(f"non-binary values found for signal(s): {', '.join(invalid)}")

    return {name: normalize_events(signal_events) for name, signal_events in events.items()}


def parse_scalar_value(
    line: str, symbol_to_name: dict[str, str]
) -> tuple[str, int] | None:
    if line.startswith(("0", "1", "x", "X", "z", "Z")):
        symbol = line[1:]
        if symbol not in symbol_to_name:
            return None
        value = line[0].lower()
        if value in ("x", "z"):
            return symbol_to_name[symbol], -1
        return symbol_to_name[symbol], int(value)

    if line.startswith(("b", "B")):
        parts = line.split()
        if len(parts) != 2 or parts[1] not in symbol_to_name:
            return None
        bits = parts[0][1:].lower()
        if any(bit in bits for bit in ("x", "z")):
            return symbol_to_name[parts[1]], -1
        try:
            return symbol_to_name[parts[1]], int(bits, 2)
        except ValueError:
            return symbol_to_name[parts[1]], -1

    return None


def normalize_events(events: Iterable[VcdEvent]) -> list[VcdEvent]:
    normalized: list[VcdEvent] = []
    last_timestamp: float | None = None
    for event in events:
        if last_timestamp is not None and event.timestamp_s < last_timestamp:
            raise VcdParseError("VCD timestamps decrease")
        last_timestamp = event.timestamp_s
        if normalized and event.timestamp_s == normalized[-1].timestamp_s:
            if len(normalized) >= 2 and normalized[-2].value == event.value:
                normalized.pop()
            else:
                normalized[-1] = event
            continue
        if normalized and normalized[-1].value == event.value:
            continue
        normalized.append(event)
    return normalized


def dedupe_same_value_events(events: Iterable[VcdEvent]) -> list[VcdEvent]:
    return normalize_events(events)


def build_segments(events: list[VcdEvent]) -> list[Segment]:
    segments: list[Segment] = []
    for current, following in zip(events, events[1:]):
        if following.timestamp_s <= current.timestamp_s:
            raise VcdParseError("VCD timestamps are not strictly increasing")
        segments.append(Segment(current.timestamp_s, following.timestamp_s, current.value))
    return segments


def integrate_value(
    segments: list[Segment],
    start_s: float,
    end_s: float,
    *,
    value: int = 1,
) -> float:
    total = 0.0
    for segment in segments:
        if segment.end_s <= start_s:
            continue
        if segment.start_s >= end_s:
            break
        if segment.value == value:
            total += max(0.0, min(segment.end_s, end_s) - max(segment.start_s, start_s))
    return total


def value_ratio(segments: list[Segment], start_s: float, end_s: float, *, value: int = 1) -> float:
    duration = end_s - start_s
    if duration <= 0:
        return 0.0
    return integrate_value(segments, start_s, end_s, value=value) / duration


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def in_range(value: float, bounds: list[float] | tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]

"""LCD1602 4-bit bus decoding helpers for logic-analyzer VCD captures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .vcd import VcdEvent, parse_vcd_signals


@dataclass
class LcdFrame:
    rows: list[str] = field(default_factory=lambda: [" " * 16, " " * 16])

    def text(self) -> str:
        return "\n".join(row.rstrip() for row in self.rows)


@dataclass(frozen=True)
class LcdTimedFrame:
    timestamp_s: float
    frame: LcdFrame


def decode_lcd1602_vcd(
    vcd_path: Path,
    *,
    signals: dict[str, str] | None = None,
    cols: int = 16,
    rows: int = 2,
) -> LcdFrame:
    frames = decode_lcd1602_vcd_frames(vcd_path, signals=signals, cols=cols, rows=rows)
    return frames[-1].frame if frames else LcdFrame(rows=[" " * cols for _ in range(rows)])


def decode_lcd1602_vcd_frames(
    vcd_path: Path,
    *,
    signals: dict[str, str] | None = None,
    cols: int = 16,
    rows: int = 2,
) -> list[LcdTimedFrame]:
    mapping = {
        "rs": "D0",
        "e": "D1",
        "d4": "D2",
        "d5": "D3",
        "d6": "D4",
        "d7": "D5",
    }
    mapping.update(signals or {})
    events_by_signal = parse_vcd_signals(vcd_path, mapping.values())
    events = {logical: events_by_signal[name] for logical, name in mapping.items()}
    frame = LcdFrame(rows=[" " * cols for _ in range(rows)])
    history = [LcdTimedFrame(0.0, clone_frame(frame))]
    cursor = 0
    pending: tuple[int, int] | None = None

    for time_s in falling_edges(events["e"]):
        rs = value_at(events["rs"], time_s)
        nibble = (
            value_at(events["d4"], time_s)
            | (value_at(events["d5"], time_s) << 1)
            | (value_at(events["d6"], time_s) << 2)
            | (value_at(events["d7"], time_s) << 3)
        )
        if pending is None or pending[0] != rs:
            pending = (rs, nibble)
            continue
        byte = (pending[1] << 4) | nibble
        pending = None
        if rs:
            cursor = write_data(frame, cursor, byte, cols, rows)
            history.append(LcdTimedFrame(time_s, clone_frame(frame)))
        else:
            cursor = apply_command(frame, cursor, byte, cols, rows)
            if byte == 0x01:
                history.append(LcdTimedFrame(time_s, clone_frame(frame)))
    return history


def clone_frame(frame: LcdFrame) -> LcdFrame:
    return LcdFrame(rows=list(frame.rows))


def falling_edges(events: list[VcdEvent]) -> list[float]:
    return [
        current.timestamp_s
        for previous, current in zip(events, events[1:])
        if previous.value == 1 and current.value == 0
    ]


def value_at(events: list[VcdEvent], time_s: float) -> int:
    value = events[0].value if events else 0
    for event in events:
        if event.timestamp_s > time_s:
            break
        value = event.value
    return value


def write_data(frame: LcdFrame, cursor: int, byte: int, cols: int, rows: int) -> int:
    row, col = address_to_position(cursor, cols)
    if 0 <= row < rows and 0 <= col < cols:
        text = frame.rows[row]
        frame.rows[row] = text[:col] + chr(byte) + text[col + 1 :]
    return cursor + 1


def apply_command(frame: LcdFrame, cursor: int, byte: int, cols: int, rows: int) -> int:
    if byte == 0x01:
        frame.rows = [" " * cols for _ in range(rows)]
        return 0
    if byte == 0x02:
        return 0
    if byte & 0x80:
        return byte & 0x7F
    return cursor


def address_to_position(address: int, cols: int) -> tuple[int, int]:
    if 0x40 <= address < 0x40 + cols:
        return 1, address - 0x40
    return 0, address


def frame_contains(frame: LcdFrame, expected: str) -> bool:
    normalized = frame.text().replace("\n", " ")
    return expected in frame.text() or expected in normalized


def frame_metrics(frame: LcdFrame) -> dict[str, Any]:
    return {"lcd_rows": [row.rstrip() for row in frame.rows], "lcd_text": frame.text()}

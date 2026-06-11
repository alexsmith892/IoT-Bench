"""Serial-log parsing helpers for Wokwi-backed validators."""

from __future__ import annotations

import re
from pathlib import Path


class SerialLogError(Exception):
    """Raised when expected serial evidence is missing or unreadable."""


def read_serial_log(path: Path) -> str:
    if not path.exists():
        raise SerialLogError(f"serial log not found: {path}")
    return normalize_text(path.read_text(encoding="utf-8", errors="replace"))


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def contains_text(text: str, expected: str, *, case_sensitive: bool = True) -> bool:
    if case_sensitive:
        return expected in text
    return expected.lower() in text.lower()


def count_occurrences(text: str, expected: str, *, case_sensitive: bool = True) -> int:
    haystack = text if case_sensitive else text.lower()
    needle = expected if case_sensitive else expected.lower()
    return haystack.count(needle)


def regex_matches(text: str, pattern: str) -> list[str]:
    return re.findall(pattern, text, flags=re.MULTILINE)


def extract_ints(text: str) -> list[int]:
    return [int(match) for match in re.findall(r"(?<![\w.])-?\d+(?![\w.])", text)]


def extract_floats(text: str) -> list[float]:
    values: list[float] = []
    for match in re.findall(r"(?<![\w.])-?(?:\d+\.\d+|\d+)(?![\w.])", text):
        try:
            values.append(float(match))
        except ValueError:
            continue
    return values


def monotonic_counter_reaches(values: list[int], expected: int) -> bool:
    if not values:
        return False
    previous = values[0]
    reached = previous >= expected
    for value in values[1:]:
        if value < previous:
            return False
        reached = reached or value >= expected
        previous = value
    return reached


def exact_count_sequence(values: list[int], expected: int, *, allow_repeats: bool = False) -> bool:
    """True only when values are exactly 1, 2, ..., expected in order.

    Rejects under-specified output (a single hardcoded value), skipped counts,
    and extra trailing values. With allow_repeats, consecutive duplicates are
    collapsed first (tolerates noisy re-prints of the current count).
    """

    if allow_repeats:
        values = [value for index, value in enumerate(values) if index == 0 or values[index - 1] != value]
    return values == list(range(1, expected + 1))


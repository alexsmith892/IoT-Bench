"""Offline source checks that intentionally remain conservative."""

from __future__ import annotations

import re
from pathlib import Path


class StaticCheckError(Exception):
    """Raised when a source-level constraint fails."""


def read_arduino_sources(sketch_path: Path) -> str:
    ino_files = [sketch_path] if sketch_path.is_file() else sorted(sketch_path.glob("*.ino"))
    if not ino_files:
        raise StaticCheckError(f"no .ino file found in {sketch_path}")
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in ino_files
    )


def validate_forbidden_calls(sketch_path: Path, forbidden_calls: list[str]) -> None:
    source = strip_comments_and_strings(read_arduino_sources(sketch_path))
    for call in forbidden_calls:
        if re.search(rf"\b{re.escape(call)}\s*\(", source):
            raise StaticCheckError(f"source contains forbidden {call}() call")


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
            result.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "code"
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

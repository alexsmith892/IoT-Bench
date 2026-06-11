"""Offline source checks that intentionally remain conservative."""

from __future__ import annotations

import re
from pathlib import Path


class StaticCheckError(Exception):
    """Raised when a source-level constraint fails."""


# Arduino compiles every source file in the sketch directory, so static checks
# must see the same set or a forbidden call can hide in a helper file. ESP-IDF
# uses the same C/C++ suffixes under an application tree, but has no .ino file.
SOURCE_SUFFIXES = {".ino", ".h", ".hpp", ".c", ".cpp"}
# Generated/build output inside a submitted sketch directory is not compiled
# as sketch source and must not be scanned.
EXCLUDED_DIR_NAMES = {"build", "artifacts", ".git", "__pycache__"}


def read_sources(sketch_path: Path, *, build_kind: str = "arduino") -> str:
    if sketch_path.is_file():
        source_files = [sketch_path]
    else:
        source_files = sorted(
            path
            for path in sketch_path.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SOURCE_SUFFIXES
            and not (set(path.relative_to(sketch_path).parts[:-1]) & EXCLUDED_DIR_NAMES)
        )
    if build_kind == "arduino" and not any(path.suffix.lower() == ".ino" for path in source_files):
        raise StaticCheckError(f"no .ino file found in {sketch_path}")
    if build_kind == "espidf":
        if not any(path.suffix.lower() in {".c", ".cpp"} for path in source_files):
            raise StaticCheckError(f"no ESP-IDF C/C++ source file found in {sketch_path}")
        if sketch_path.is_dir() and not (sketch_path / "CMakeLists.txt").exists():
            raise StaticCheckError(f"no ESP-IDF CMakeLists.txt found in {sketch_path}")
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in source_files
    )


def read_arduino_sources(sketch_path: Path) -> str:
    return read_sources(sketch_path, build_kind="arduino")


def validate_forbidden_calls(sketch_path: Path, forbidden_calls: list[str], *, build_kind: str = "arduino") -> None:
    source = strip_comments_and_strings(read_sources(sketch_path, build_kind=build_kind))
    for call in forbidden_calls:
        if re.search(rf"\b{re.escape(call)}\s*\(", source):
            raise StaticCheckError(f"source contains forbidden {call}() call")


def validate_required_patterns(sketch_path: Path, patterns: list[str], *, build_kind: str = "arduino") -> None:
    source = strip_comments_and_strings(read_sources(sketch_path, build_kind=build_kind))
    missing = [pattern for pattern in patterns if not re.search(pattern, source)]
    if missing:
        raise StaticCheckError(
            "source is missing required pattern(s): " + ", ".join(missing)
        )


def validate_required_any_patterns(sketch_path: Path, pattern_groups: list[list[str]], *, build_kind: str = "arduino") -> None:
    source = strip_comments_and_strings(read_sources(sketch_path, build_kind=build_kind))
    for group in pattern_groups:
        if not group:
            continue
        if not any(re.search(pattern, source) for pattern in group):
            raise StaticCheckError(
                "source is missing one of required patterns: " + ", ".join(group)
            )


def validate_static_checks(sketch_path: Path, checks: dict, *, build_kind: str = "arduino") -> None:
    forbidden = checks.get("forbidden_calls") or []
    required = checks.get("required_patterns") or []
    required_any = checks.get("required_any_patterns") or []
    if forbidden:
        validate_forbidden_calls(sketch_path, list(forbidden), build_kind=build_kind)
    if required:
        validate_required_patterns(sketch_path, list(required), build_kind=build_kind)
    if required_any:
        validate_required_any_patterns(sketch_path, [list(group) for group in required_any], build_kind=build_kind)


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

from __future__ import annotations

import re
from pathlib import Path

from bench.config import TaskConfig
from bench.results import COMPILE_FAIL, SOURCE_USER_CODE, result_payload

from .schemas import ExtractionResult


FENCE_RE = re.compile(r"```(?P<lang>[^\n`]*)\n(?P<body>.*?)```", re.DOTALL)


def extract_to_source(task: TaskConfig, response_text: str, source_dir: Path) -> ExtractionResult:
    return extract_submission(task, response_text, source_dir)


def extract_submission(task: TaskConfig, response_text: str, source_dir: Path) -> ExtractionResult:
    source_dir.mkdir(parents=True, exist_ok=True)
    build_kind = task.board_profile.build_kind
    if build_kind == "arduino":
        extracted = extract_arduino_source(response_text)
        suffix = ".ino"
        failure_reason = "model response did not contain one usable Arduino sketch"
    elif build_kind in {"espidf", "zephyr"}:
        extracted = extract_c_source(response_text)
        suffix = ".c"
        failure_reason = f"model response did not contain one usable {build_kind} C source file"
    else:
        extracted = None
        suffix = ".txt"
        failure_reason = f"unsupported build kind for extraction: {build_kind}"
    if extracted is None:
        result = result_payload(
            COMPILE_FAIL,
            failure_reason,
            failure_stage="format",
            failure_source=SOURCE_USER_CODE,
        )
        return ExtractionResult(False, None, result, result["reason"])
    source_path = source_dir / f"{task.task_id}{suffix}"
    source_path.write_text(extracted.rstrip() + "\n", encoding="utf-8", newline="\n")
    return ExtractionResult(True, source_path, None)


def extract_arduino_source(text: str) -> str | None:
    return _extract_single_source(text, _looks_like_arduino)


def extract_c_source(text: str) -> str | None:
    return _extract_single_source(text, _looks_like_c_source)


def _extract_single_source(text: str, predicate) -> str | None:
    if not text or not text.strip():
        return None
    fences = [match.group("body").strip() for match in FENCE_RE.finditer(text)]
    source_fences = [body for body in fences if predicate(body)]
    if len(source_fences) == 1:
        return _strip_file_header(source_fences[0])
    if len(source_fences) > 1:
        return None
    if fences:
        return None
    raw = text.strip()
    if predicate(raw):
        return _strip_file_header(raw)
    return None


def _looks_like_arduino(text: str) -> bool:
    body = text.strip()
    if not body:
        return False
    has_function = re.search(r"\bvoid\s+(setup|loop)\s*\(", body) is not None
    has_code = "{" in body and "}" in body
    return has_function and has_code


def _looks_like_c_source(text: str) -> bool:
    body = text.strip()
    if not body:
        return False
    has_main = re.search(r"\b(void|int)\s+(app_)?main\s*\(", body) is not None
    has_include = "#include" in body
    return has_main and has_include and "{" in body and "}" in body


def _strip_file_header(text: str) -> str:
    lines = text.strip().splitlines()
    while lines and re.match(r"^\s*(//\s*)?(file|filename)\s*:", lines[0], re.IGNORECASE):
        lines.pop(0)
    return "\n".join(lines).strip()

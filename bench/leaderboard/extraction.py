from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
        extracted = _extract_single_source_detail(response_text, _looks_like_arduino)
        suffix = ".ino"
        failure_reason = "model response did not contain one usable Arduino sketch"
    elif build_kind in {"espidf", "zephyr"}:
        extracted = _extract_single_source_detail(response_text, _looks_like_c_source)
        suffix = ".c"
        failure_reason = f"model response did not contain one usable {build_kind} C source file"
    else:
        extracted = {
            "source": None,
            "metadata": {
                "chosen_fence_language": None,
                "candidate_fence_count": 0,
                "failure_reason": f"unsupported build kind for extraction: {build_kind}",
            },
        }
        suffix = ".txt"
        failure_reason = f"unsupported build kind for extraction: {build_kind}"
    metadata = extracted["metadata"]
    if extracted["source"] is None:
        metadata["failure_reason"] = metadata.get("failure_reason") or failure_reason
        result = result_payload(
            COMPILE_FAIL,
            metadata["failure_reason"],
            failure_stage="format",
            failure_source=SOURCE_USER_CODE,
        )
        return ExtractionResult(False, None, result, result["reason"], metadata)
    source_path = source_dir / f"{task.task_id}{suffix}"
    source_path.write_text(str(extracted["source"]).rstrip() + "\n", encoding="utf-8", newline="\n")
    return ExtractionResult(True, source_path, None, metadata=metadata)


def extract_arduino_source(text: str) -> str | None:
    detail = _extract_single_source_detail(text, _looks_like_arduino)
    return detail["source"]


def extract_c_source(text: str) -> str | None:
    detail = _extract_single_source_detail(text, _looks_like_c_source)
    return detail["source"]


def _extract_single_source_detail(text: str, predicate) -> dict[str, Any]:
    if not text or not text.strip():
        return _extraction_detail(None, None, 0, "model response was empty")
    fences = [
        {
            "language": match.group("lang").strip() or None,
            "body": match.group("body").strip(),
        }
        for match in FENCE_RE.finditer(text)
    ]
    source_fences = [fence for fence in fences if predicate(fence["body"])]
    if len(source_fences) == 1:
        return _extraction_detail(
            _strip_file_header(source_fences[0]["body"]),
            source_fences[0]["language"],
            len(source_fences),
            None,
        )
    if len(source_fences) > 1:
        return _extraction_detail(None, None, len(source_fences), "model response contained multiple usable source fences")
    if fences:
        return _extraction_detail(None, None, 0, "model response did not contain a usable source fence")
    raw = text.strip()
    if predicate(raw):
        return _extraction_detail(_strip_file_header(raw), None, 0, None)
    return _extraction_detail(None, None, 0, "model response did not contain usable source")


def _extraction_detail(
    source: str | None,
    chosen_fence_language: str | None,
    candidate_fence_count: int,
    failure_reason: str | None,
) -> dict[str, Any]:
    return {
        "source": source,
        "metadata": {
            "chosen_fence_language": chosen_fence_language,
            "candidate_fence_count": candidate_fence_count,
            "failure_reason": failure_reason,
        },
    }


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

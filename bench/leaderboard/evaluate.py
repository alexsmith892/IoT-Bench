from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from bench.cli import timed_run_single_task
from bench.config import TaskConfig
from bench.runner import generate_case


def _workspace_dir(run_dir: Path, attempt_slug: str, index: int) -> Path:
    """Per-attempt isolated build workspace.

    The case tree generated underneath this is deep
    (``cases/<case_id>/artifacts/submissions/<sketch_name>/main/main.c``), and on
    Windows a verbose ``<task>.<mode>.<rep>`` segment can push the longest-named
    ESP-IDF tasks past MAX_PATH (260) during submission extraction, leaving an
    empty ``main/`` and a spurious artifact failure. The workspace is transient
    and never published, so use a short hash segment to claw back ~30 chars and
    keep every task's paths comfortably under the limit. (Prompts/responses/
    sources keep the readable slug — they're shallow.)"""

    short = hashlib.sha1(attempt_slug.encode("utf-8")).hexdigest()[:10]
    return run_dir / "workspace" / short / f"if_{index}"


def evaluate_source(
    task: TaskConfig,
    *,
    source_path: Path,
    run_dir: Path,
    attempt_slug: str,
    if_retries: int,
    simulation_time_ms: int | None,
    arduino_cli: str = "arduino-cli",
    idf_py: str = "idf.py",
    wokwi_cli: str = "wokwi-cli",
    west: str = "west",
    renode_cli: str = "renode",
    allow_tool_version_mismatch: bool = False,
) -> dict[str, Any]:
    if if_retries < 0:
        raise ValueError("if_retries must be non-negative")
    attempts: list[dict[str, Any]] = []
    max_attempts = if_retries + 1
    for index in range(1, max_attempts + 1):
        ws = _workspace_dir(run_dir, attempt_slug, index)
        paths = generate_case(task, root=ws)
        attempt = timed_run_single_task(
            task,
            case_dir=paths.case_dir,
            sketch_override=source_path,
            use_existing_artifacts=False,
            regenerate=False,
            simulation_time_ms=simulation_time_ms,
            arduino_cli=arduino_cli,
            idf_py=idf_py,
            wokwi_cli=wokwi_cli,
            west=west,
            renode_cli=renode_cli,
            archived_vcd=None,
            require_provenance=True,
            allow_tool_version_mismatch=allow_tool_version_mismatch,
            attempt_index=index,
        )
        attempts.append(attempt)
        if attempt["result"]["result"] != "IF":
            break
    return {
        "attempts": attempts,
        "final_result": attempts[-1]["result"],
        "if_retries_used": max(0, len(attempts) - 1),
    }


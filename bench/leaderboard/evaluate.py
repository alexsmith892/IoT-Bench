from __future__ import annotations

from pathlib import Path
from typing import Any

from bench.cli import timed_run_single_task
from bench.config import TaskConfig
from bench.runner import generate_case


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
        ws = run_dir / "workspace" / attempt_slug / f"if_{index}"
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


"""Tracked, compact evidence index for a platform.

`cases/*/artifacts/verification.json` is per-machine and gitignored, so it is not
portable leaderboard proof. This module aggregates those local manifests into one
small, tracked file (`docs/<platform>-evidence.json`) that records, per task, the
result, when it was produced, the input/firmware hashes, the toolchain, and a
*freshness* verdict: evidence is fresh only if the recorded input hashes still
match the current task/prompt/reference sources and the recorded tool versions
match the pinned `bench/tool_versions.yaml`. Any drift marks the task stale, i.e.
it must be re-run before it counts toward the leaderboard.

The benchmark harness hash is recorded and compared too, but as an informational
`harness_match` flag rather than a freshness gate: any edit to `bench/*.py`
changes that hash even when it cannot affect a given task's scoring (e.g. a CLI
tweak), so gating on it would falsely invalidate unrelated evidence. A stricter
consumer can additionally require `harness_match` before publishing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import TaskConfig, canonical_task_ids, iter_platform_tasks
from .runner import (
    benchmark_harness_hash,
    case_dir_for_task,
    hash_file,
    hash_path,
    load_case_paths,
    pinned_tool_versions,
    tool_version_keys_for_build,
)

EVIDENCE_INDEX_VERSION = 1

# Input hashes that, if changed, invalidate a recorded result.
_INPUT_HASH_KEYS = ("task_hash", "prompt_hash", "sketch_hash")


def evidence_stale_reasons(
    manifest: dict[str, Any],
    *,
    current: dict[str, str | None],
    pinned: dict[str, str | None],
    build_kind: str,
) -> list[str]:
    """Return the list of drift reasons; empty means the evidence is fresh."""

    reasons: list[str] = []
    for key in _INPUT_HASH_KEYS:
        if key in current and manifest.get(key) != current[key]:
            reasons.append(key)
    for key, label in tool_version_keys_for_build(build_kind):
        if pinned.get(key) is not None and manifest.get(key) != pinned.get(key):
            reasons.append(f"tool:{label}")
    return reasons


def evidence_entry(
    task: TaskConfig, *, canonical_ids: set[str] | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "task_id": task.task_id,
        "platform": task.platform,
        "level": task.level,
    }
    # Only platforms with a vendored canonical manifest distinguish canonical
    # tasks from sanctioned additions; for others the field is omitted so their
    # index stays byte-identical to before this split was introduced.
    if canonical_ids is not None:
        entry["canonical"] = task.task_id in canonical_ids
    if not task.is_supported:
        entry["evidence"] = "unsupported"
        entry["fresh"] = False
        return entry

    case_dir = case_dir_for_task(task)
    manifest_path = case_dir / "artifacts" / "verification.json"
    if not manifest_path.exists():
        entry["evidence"] = "missing"
        entry["fresh"] = False
        return entry
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        entry["evidence"] = "unreadable"
        entry["fresh"] = False
        return entry

    current: dict[str, str | None] = {
        "task_hash": hash_file(task.path),
        "prompt_hash": hash_file(task.prompt_path),
    }
    try:
        current["sketch_hash"] = hash_path(load_case_paths(task, case_dir).sketch)
    except Exception:
        # Reference sketch not resolvable offline: skip that hash rather than
        # falsely flag drift.
        pass

    build_kind = task.board_profile.build_kind
    reasons = evidence_stale_reasons(
        manifest,
        current=current,
        pinned=pinned_tool_versions(),
        build_kind=build_kind,
    )
    entry.update(
        {
            "evidence": "present",
            "result": manifest.get("result"),
            "classification": manifest.get("classification"),
            "timestamp": manifest.get("timestamp"),
            "fresh": not reasons,
            "stale_reasons": reasons,
            "harness_match": manifest.get("benchmark_harness_hash") == benchmark_harness_hash(),
            "hashes": {
                "task_hash": manifest.get("task_hash"),
                "prompt_hash": manifest.get("prompt_hash"),
                "sketch_hash": manifest.get("sketch_hash"),
                "firmware_image_hash": manifest.get("firmware_image_hash"),
            },
            "tool_versions": {
                label: manifest.get(key)
                for key, label in tool_version_keys_for_build(build_kind)
            },
        }
    )
    return entry


def build_evidence_index(platform: str, *, level: str = "all") -> dict[str, Any]:
    tasks = sorted(
        iter_platform_tasks(platform=platform),
        key=lambda t: (t.level, t.task_id),
    )
    if level != "all":
        tasks = [t for t in tasks if t.level == level]
    canonical_ids = canonical_task_ids(platform)
    entries = [evidence_entry(task, canonical_ids=canonical_ids) for task in tasks]

    def count(pred) -> int:
        return sum(1 for entry in entries if pred(entry))

    summary = {
        "platform": platform,
        "total": len(entries),
        "present": count(lambda e: e.get("evidence") == "present"),
        "missing": count(lambda e: e.get("evidence") == "missing"),
        "fresh_bc": count(lambda e: e.get("fresh") and e.get("result") == "BC"),
        "stale": count(lambda e: e.get("evidence") == "present" and not e.get("fresh")),
    }
    # Canonical/addition split (D4): only emitted for platforms that have a
    # canonical manifest, so non-canonical platforms keep their prior summary
    # shape. fresh_bc above counts all tasks; canonical_fresh_bc is the
    # leaderboard-relevant subset.
    if canonical_ids is not None:
        summary["canonical_total"] = count(lambda e: e.get("canonical"))
        summary["canonical_fresh_bc"] = count(
            lambda e: e.get("canonical") and e.get("fresh") and e.get("result") == "BC"
        )
        summary["addition_total"] = count(lambda e: not e.get("canonical"))
    return {
        "index_version": EVIDENCE_INDEX_VERSION,
        "summary": summary,
        "tasks": entries,
    }


def default_index_path(platform: str) -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / f"{platform}-evidence.json"


def write_evidence_index(platform: str, *, level: str = "all", output: Path | None = None) -> Path:
    index = build_evidence_index(platform, level=level)
    destination = output or default_index_path(platform)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return destination

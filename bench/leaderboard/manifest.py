from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import yaml

from bench.config import ConfigError, load_task

from .schemas import ManifestTask, PlanResult, ResolvedTask


FORBIDDEN_MANIFEST_KEYS = {
    "oracle",
    "scenario",
    "validator",
    "validator_params",
    "expected",
    "expected_outputs",
    "params",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def benchmark_root(benchmark_id: str, *, root: Path | None = None) -> Path:
    return (root or repo_root()) / "benchmarks" / benchmark_id


def load_manifest(benchmark_id: str, *, root: Path | None = None) -> dict[str, Any]:
    path = benchmark_root(benchmark_id, root=root) / "manifest.yaml"
    if not path.exists():
        raise ConfigError(f"leaderboard manifest not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"leaderboard manifest must be a mapping: {path}")
    if data.get("benchmark_id") != benchmark_id:
        raise ConfigError(f"{path}: benchmark_id does not match {benchmark_id!r}")
    if data.get("schema_version") != 1:
        raise ConfigError(f"{path}: unsupported schema_version {data.get('schema_version')!r}")
    _assert_no_oracle_keys(data, path=path)
    return data


def _assert_no_oracle_keys(value: Any, *, path: Path) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in FORBIDDEN_MANIFEST_KEYS:
                raise ConfigError(f"{path}: forbidden oracle-like manifest key {key!r}")
            _assert_no_oracle_keys(child, path=path)
    elif isinstance(value, list):
        for child in value:
            _assert_no_oracle_keys(child, path=path)


def parse_levels(levels: str | Iterable[str]) -> tuple[str, ...]:
    raw = levels.split(",") if isinstance(levels, str) else list(levels)
    parsed: list[str] = []
    for item in raw:
        value = str(item).strip()
        if not value:
            continue
        if value in {"1", "2", "3"}:
            value = f"level{value}"
        if value not in {"level1", "level2", "level3"}:
            raise ConfigError(f"unknown level {item!r}")
        parsed.append(value)
    if not parsed:
        raise ConfigError("at least one level is required")
    return tuple(dict.fromkeys(parsed))


def parse_csv(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    parsed = tuple(part.strip() for part in value.split(",") if part.strip())
    return parsed or None


def manifest_tasks(data: dict[str, Any]) -> tuple[ManifestTask, ...]:
    rows = data.get("tasks")
    if not isinstance(rows, list):
        raise ConfigError("manifest tasks must be a list")
    tasks: list[ManifestTask] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ConfigError("manifest task entries must be mappings")
        tasks.append(
            ManifestTask(
                canonical_id=str(row["canonical_id"]),
                local_task_id=str(row["local_task_id"]),
                local_platform=str(row["local_platform"]),
                level=str(row["level"]),
                score_eligible=bool(row.get("score_eligible", True)),
                required_evidence=str(row.get("required_evidence", "publishable")),
                prompt_source=str(row.get("prompt_source", "local_prompt")),
                skill_selection=dict(row.get("skill_selection") or {}),
                deviations=tuple(row.get("deviations") or ()),
            )
        )
    return tuple(tasks)


def selected_skill_modes(data: dict[str, Any], requested: str | None) -> tuple[str, ...]:
    modes = data.get("skill_modes")
    if not isinstance(modes, dict):
        raise ConfigError("manifest skill_modes must be a mapping")
    wanted = parse_csv(requested) or tuple(modes.keys())
    missing = [mode for mode in wanted if mode not in modes]
    if missing:
        raise ConfigError(f"unknown skill mode(s): {', '.join(missing)}")
    return tuple(wanted)


def resolve_plan(
    benchmark_id: str,
    *,
    platform: str,
    levels: str | Iterable[str],
    skill_modes: str | None = None,
    task_ids: str | None = None,
    reps: int = 1,
    limit: int | None = None,
    out: Path | None = None,
    allow_unpublishable: bool = False,
    root: Path | None = None,
) -> PlanResult:
    if reps <= 0:
        raise ConfigError("--reps must be positive")
    data = load_manifest(benchmark_id, root=root)
    level_set = parse_levels(levels)
    mode_set = selected_skill_modes(data, skill_modes)
    wanted_tasks = parse_csv(task_ids)

    all_tasks = [
        entry
        for entry in manifest_tasks(data)
        if entry.local_platform == platform and entry.level in level_set
    ]
    if wanted_tasks is not None:
        wanted = set(wanted_tasks)
        all_tasks = [entry for entry in all_tasks if entry.local_task_id in wanted]
        missing = wanted - {entry.local_task_id for entry in all_tasks}
        if missing:
            raise ConfigError(f"manifest does not contain requested task(s): {', '.join(sorted(missing))}")
    if limit is not None:
        if limit < 0:
            raise ConfigError("--limit must be non-negative")
        all_tasks = all_tasks[:limit]
    if not all_tasks:
        raise ConfigError("selection contains no tasks")

    evidence = _evidence_by_task(platform)
    resolved: list[ResolvedTask] = []
    unpublishable: list[str] = []
    for entry in all_tasks:
        task = load_task(entry.local_task_id, platform=entry.local_platform, level=entry.level, root=root)
        if task.prompt_path != task.path.with_suffix(".prompt.md") or not task.prompt_path.exists():
            raise ConfigError(f"{task.task_id}: prompt sidecar is missing")
        evidence_entry = evidence.get(entry.local_task_id, {})
        publishable = _entry_publishable(entry, evidence_entry)
        if entry.score_eligible and entry.required_evidence == "publishable" and not publishable:
            unpublishable.append(entry.local_task_id)
        resolved.append(ResolvedTask(entry, task, publishable, evidence_entry))
    if unpublishable and not allow_unpublishable:
        raise ConfigError(
            "score-eligible task(s) lack publishable evidence: "
            + ", ".join(sorted(unpublishable))
            + " (pass --allow-unpublishable to run as non-publishable)"
        )

    canonical_count = len({entry.canonical_id for entry in all_tasks})
    score_eligible_count = sum(1 for entry in all_tasks if entry.score_eligible)
    generation_count = len(all_tasks) * len(mode_set) * reps
    return PlanResult(
        benchmark_id=benchmark_id,
        benchmark_root=benchmark_root(benchmark_id, root=root),
        platform=platform,
        levels=level_set,
        skill_modes=mode_set,
        tasks=tuple(resolved),
        generation_count=generation_count,
        publishable=not unpublishable,
        counts={
            "canonical": canonical_count,
            "selected": len(all_tasks),
            "score_eligible": score_eligible_count,
            "scored_out": sum(1 for entry in all_tasks if not entry.score_eligible),
            "generations": generation_count,
        },
        output_root=out,
    )


def _evidence_by_task(platform: str) -> dict[str, dict[str, Any]]:
    path = repo_root() / "docs" / f"{platform}-evidence.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(entry.get("task_id")): entry
        for entry in data.get("tasks", [])
        if isinstance(entry, dict) and entry.get("task_id")
    }


def _entry_publishable(entry: ManifestTask, evidence: dict[str, Any]) -> bool:
    if not entry.score_eligible:
        return True
    return (
        evidence.get("evidence") == "present"
        and evidence.get("fresh") is True
        and evidence.get("result") == "BC"
        and evidence.get("harness_match") is True
    )


def plan_payload(plan: PlanResult) -> dict[str, Any]:
    return {
        "benchmark": plan.benchmark_id,
        "platform": plan.platform,
        "levels": list(plan.levels),
        "skill_modes": list(plan.skill_modes),
        "tasks": len(plan.tasks),
        "generation_count": plan.generation_count,
        "publishable": plan.publishable,
        "counts": plan.counts,
        "output_root": str(plan.output_root) if plan.output_root else None,
        "task_ids": [item.task.task_id for item in plan.tasks],
    }


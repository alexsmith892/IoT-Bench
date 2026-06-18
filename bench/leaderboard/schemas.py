from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bench.config import TaskConfig


@dataclass(frozen=True)
class ManifestTask:
    canonical_id: str
    local_task_id: str
    local_platform: str
    level: str
    score_eligible: bool
    required_evidence: str
    prompt_source: str
    skill_selection: dict[str, Any]
    deviations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedTask:
    manifest: ManifestTask
    task: TaskConfig
    publishable: bool
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillFile:
    name: str
    path: Path
    sha256: str
    text: str


@dataclass(frozen=True)
class PlanResult:
    benchmark_id: str
    benchmark_root: Path
    platform: str
    levels: tuple[str, ...]
    skill_modes: tuple[str, ...]
    tasks: tuple[ResolvedTask, ...]
    generation_count: int
    publishable: bool
    counts: dict[str, int]
    output_root: Path | None = None


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    raw: dict[str, Any]
    usage: dict[str, Any] | None
    latency_s: float
    num_model_calls: int = 1


@dataclass(frozen=True)
class ExtractionResult:
    ok: bool
    source_path: Path | None
    result: dict[str, Any] | None
    reason: str | None = None


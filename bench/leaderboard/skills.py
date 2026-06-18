from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bench.config import ConfigError

from .schemas import ManifestTask, SkillFile


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock_sha(path: Path) -> str:
    return sha256_file(path)


def verify_skill_lock(benchmark_root: Path) -> dict[str, str]:
    lock_path = benchmark_root / "skills.lock.json"
    if not lock_path.exists():
        raise ConfigError(f"skill lock not found: {lock_path}")
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    files = data.get("files")
    if not isinstance(files, list):
        raise ConfigError(f"{lock_path}: files must be a list")
    locked: dict[str, str] = {}
    for row in files:
        rel = str(row["path"])
        expected = str(row["sha256"])
        path = benchmark_root / rel
        if not path.exists():
            raise ConfigError(f"locked skill file is missing: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ConfigError(f"skill lock mismatch for {rel}: expected {expected}, got {actual}")
        locked[rel] = expected
    return locked


def upstream_lock_sha(benchmark_root: Path) -> str:
    path = benchmark_root / "upstream.lock.json"
    if not path.exists():
        raise ConfigError(f"upstream lock not found: {path}")
    return sha256_file(path)


def skills_lock_sha(benchmark_root: Path) -> str:
    return lock_sha(benchmark_root / "skills.lock.json")


def select_skills(
    benchmark_root: Path,
    *,
    skill_modes: dict[str, Any],
    skill_mode: str,
    task_entry: ManifestTask,
    max_files: int = 4,
) -> tuple[SkillFile, ...]:
    mode_config = skill_modes.get(skill_mode)
    if not isinstance(mode_config, dict):
        raise ConfigError(f"unknown skill mode {skill_mode!r}")
    if not mode_config.get("use_skills"):
        return ()
    locked = verify_skill_lock(benchmark_root)
    skills_dir = mode_config.get("skills_dir")
    if not skills_dir:
        raise ConfigError(f"skill mode {skill_mode!r} requires skills_dir")
    root = benchmark_root / str(skills_dir)
    if not root.is_dir():
        raise ConfigError(f"skill directory not found: {root}")

    tags = {
        _normalize_tag(tag)
        for tag in task_entry.skill_selection.get("tags", [])
        if str(tag).strip()
    }
    candidates: list[tuple[int, str, Path]] = []
    for path in sorted(root.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        name = _normalize_tag(path.stem)
        text_hint = _normalize_tag(path.name)
        score = sum(1 for tag in tags if tag and (tag in name or tag in text_hint))
        if "arduino" in tags and "arduino" in name:
            score += 4
        if "gpio" in tags and ("gpio" in name or "switch" in name or "timer" in name):
            score += 2
        if "sensor" in tags and any(part in name for part in ("dht", "ds18", "ds1307", "mpu", "bme", "photoresistor")):
            score += 2
        if score > 0:
            candidates.append((score, path.name, path))
    if not candidates:
        candidates = [(1, path.name, path) for path in sorted(root.glob("*.md")) if path.name.lower() != "readme.md"]
    chosen = sorted(candidates, key=lambda row: (-row[0], row[1]))[:max_files]
    result: list[SkillFile] = []
    for _, _, path in chosen:
        rel = path.relative_to(benchmark_root).as_posix()
        digest = locked.get(rel)
        if digest is None:
            raise ConfigError(f"selected skill is not locked: {rel}")
        result.append(
            SkillFile(
                name=path.name,
                path=path,
                sha256=digest,
                text=path.read_text(encoding="utf-8"),
            )
        )
    return tuple(result)


def _normalize_tag(value: str) -> str:
    return str(value).lower().replace("_", "-").replace(" ", "-")


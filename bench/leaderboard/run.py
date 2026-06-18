from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.config import ConfigError
from bench.runner import benchmark_harness_hash, current_tool_versions

from .evaluate import evaluate_source
from .extraction import extract_to_source
from .manifest import load_manifest, plan_payload
from .pricing import PRICING_TABLE_VERSION, cost_usd
from .prompts import compose_prompt
from .providers import generate_response
from .reports import write_reports
from .schemas import PlanResult, ResolvedTask
from .skills import select_skills, skills_lock_sha, upstream_lock_sha


def run_experiment(
    plan: PlanResult,
    *,
    model: str,
    out: Path,
    dry_run: bool,
    confirm_spend: bool,
    max_generations: int | None,
    reps: int,
    temperature: float,
    top_p: float,
    max_tokens: int,
    seed: int | None,
    if_retries: int,
    api_base: str | None,
    api_key_env: str,
    simulation_time_ms: int | None,
    allow_tool_version_mismatch: bool,
    allow_unpublishable: bool,
) -> dict[str, Any]:
    if not dry_run and not confirm_spend:
        raise ConfigError("leaderboard run requires --confirm-spend unless --dry-run is set")
    if max_generations is not None and plan.generation_count > max_generations:
        raise ConfigError(
            f"planned generation count {plan.generation_count} exceeds --max-generations {max_generations}"
        )
    if dry_run:
        payload = plan_payload(plan)
        payload["dry_run"] = True
        payload["model"] = model
        return payload

    out.mkdir(parents=True, exist_ok=True)
    for child in ("prompts", "responses", "sources"):
        (out / child).mkdir(exist_ok=True)
    started_at = _utc_now()
    manifest_data = load_manifest(plan.benchmark_id)
    skill_modes_config = manifest_data["skill_modes"]

    experiment = {
        "run_name": out.name,
        "benchmark": plan.benchmark_id,
        "model": model,
        "platform": plan.platform,
        "levels": list(plan.levels),
        "skill_modes": list(plan.skill_modes),
        "reps": reps,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "seed": seed,
        "if_retries": if_retries,
        "allow_unpublishable": allow_unpublishable,
        "publishable": plan.publishable and not allow_unpublishable,
        "started_at": started_at,
        "harness_git_sha": _git_sha(),
        "benchmark_harness_hash": benchmark_harness_hash(),
        "tool_versions": current_tool_versions(build_kind="arduino"),
        "pricing_table_version": PRICING_TABLE_VERSION,
        "manifest_lock_sha": _sha_if_exists(plan.benchmark_root / "manifest.yaml"),
        "upstream_lock_sha": upstream_lock_sha(plan.benchmark_root),
        "skills_lock_sha": skills_lock_sha(plan.benchmark_root),
        "selection_counts": plan.counts,
        "cli_args": {},
    }
    (out / "experiment.json").write_text(json.dumps(experiment, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    attempts_path = out / "attempts.jsonl"
    with attempts_path.open("w", encoding="utf-8", newline="\n") as stream:
        for resolved in plan.tasks:
            for skill_mode in plan.skill_modes:
                for rep_index in range(1, reps + 1):
                    row = _run_one(
                        out,
                        resolved,
                        benchmark_root=plan.benchmark_root,
                        skill_mode=skill_mode,
                        skill_modes_config=skill_modes_config,
                        model=model,
                        rep_index=rep_index,
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                        seed=seed,
                        if_retries=if_retries,
                        api_base=api_base,
                        api_key_env=api_key_env,
                        simulation_time_ms=simulation_time_ms,
                        allow_tool_version_mismatch=allow_tool_version_mismatch,
                    )
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
                    stream.flush()

    experiment["ended_at"] = _utc_now()
    (out / "experiment.json").write_text(json.dumps(experiment, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    reports = write_reports(out)
    return {"run": str(out), "attempts": str(attempts_path), "reports": reports}


def _run_one(
    out: Path,
    resolved: ResolvedTask,
    *,
    benchmark_root: Path,
    skill_mode: str,
    skill_modes_config: dict[str, Any],
    model: str,
    rep_index: int,
    temperature: float,
    top_p: float,
    max_tokens: int,
    seed: int | None,
    if_retries: int,
    api_base: str | None,
    api_key_env: str,
    simulation_time_ms: int | None,
    allow_tool_version_mismatch: bool,
) -> dict[str, Any]:
    task = resolved.task
    slug = f"{task.task_id}.{skill_mode}.{rep_index}"
    skills = select_skills(
        benchmark_root,
        skill_modes=skill_modes_config,
        skill_mode=skill_mode,
        task_entry=resolved.manifest,
    )
    prompt, base_prompt_chars, skill_prompt_chars = compose_prompt(task, skills)
    prompt_path = out / "prompts" / f"{slug}.md"
    prompt_path.write_text(prompt, encoding="utf-8", newline="\n")

    response = generate_response(
        model,
        prompt=prompt,
        task=task,
        api_base=api_base,
        api_key_env=api_key_env,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
    )
    response_path = out / "responses" / f"{slug}.raw.json"
    response_path.write_text(json.dumps(response.raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    source_dir = out / "sources" / slug
    extraction = extract_to_source(task, response.text, source_dir)
    if extraction.ok and extraction.source_path is not None:
        evaluation = evaluate_source(
            task,
            source_path=extraction.source_path,
            run_dir=out,
            attempt_slug=slug,
            if_retries=if_retries,
            simulation_time_ms=simulation_time_ms,
            allow_tool_version_mismatch=allow_tool_version_mismatch,
        )
        result = evaluation["final_result"]
        if_retries_used = evaluation["if_retries_used"]
    else:
        result = extraction.result or {}
        if_retries_used = 0

    usage = response.usage or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    row = {
        "run_name": out.name,
        "model": model,
        "provider": model.split(":", 1)[0],
        "platform": task.platform,
        "level": task.level,
        "canonical_id": resolved.manifest.canonical_id,
        "local_task_id": task.task_id,
        "skill_mode": skill_mode,
        "skills_used": [{"name": skill.name, "sha256": skill.sha256} for skill in skills],
        "rep_index": rep_index,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "seed": seed,
        "base_input_tokens": None,
        "skill_input_tokens": None,
        "base_prompt_chars": base_prompt_chars,
        "skill_prompt_chars": skill_prompt_chars,
        "output_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd(model, usage if usage else None),
        "pricing_table_version": PRICING_TABLE_VERSION,
        "num_model_calls": response.num_model_calls,
        "latency_s": response.latency_s,
        "generation_retries": 0,
        "if_retries_used": if_retries_used,
        "result": result.get("result"),
        "classification": result.get("classification"),
        "failure_stage": result.get("failure_stage"),
        "failure_source": result.get("failure_source"),
        "reason": result.get("reason"),
        "metrics": result.get("metrics") or {},
        "prompt_path": _rel(prompt_path, out),
        "response_path": _rel(response_path, out),
        "source_path": _rel(extraction.source_path, out) if extraction.source_path else "",
        "publishable": resolved.publishable,
    }
    return row


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_sha() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _sha_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    return path.relative_to(root).as_posix()

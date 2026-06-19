from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.config import ConfigError
from bench.runner import benchmark_harness_hash, current_tool_versions
from bench.results import SIM_INFRA_FAIL, SOURCE_HARNESS, result_payload

from .evaluate import evaluate_source
from .extraction import extract_submission
from .manifest import load_manifest, plan_payload
from .prompts import compose_prompt
from .providers import generate_response
from .tokenization import split_token_counts
from .reports import write_reports
from .schemas import PlanResult, ProviderFailure, ResolvedTask
from .skills import select_skills, skills_lock_sha, upstream_lock_sha


OWNED_RUN_CHILDREN = {
    "attempts.jsonl",
    "experiment.json",
    "prompts",
    "responses",
    "sources",
    "workspace",
    "reports",
}
ATTEMPT_KEY_FIELDS = ("local_task_id", "skill_mode", "rep_index")
REPORT_IF_THRESHOLD_DEFAULT = 0.05


def run_experiment(
    plan: PlanResult,
    *,
    model: str,
    out: Path,
    dry_run: bool,
    confirm_spend: bool,
    resume: bool,
    force: bool,
    max_generations: int | None,
    reps: int,
    temperature: float,
    top_p: float,
    max_tokens: int,
    seed: int | None,
    if_retries: int,
    api_base: str | None,
    api_key_env: str | None,
    simulation_time_ms: int | None,
    allow_tool_version_mismatch: bool,
    allow_unpublishable: bool,
    cli_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not dry_run and not confirm_spend:
        raise ConfigError("leaderboard run requires --confirm-spend unless --dry-run is set")
    if resume and force:
        raise ConfigError("--resume and --force are mutually exclusive")
    if max_generations is not None and plan.generation_count > max_generations:
        raise ConfigError(
            f"planned generation count {plan.generation_count} exceeds --max-generations {max_generations}"
        )
    if dry_run:
        payload = plan_payload(plan)
        payload["dry_run"] = True
        payload["model"] = model
        return payload

    if out.exists() and any(out.iterdir()) and not resume and not force:
        raise ConfigError(f"run directory is not empty: {out} (use --resume or --force)")
    if force:
        _clear_owned_run_outputs(out)
    out.mkdir(parents=True, exist_ok=True)
    for child in ("prompts", "responses", "sources"):
        (out / child).mkdir(exist_ok=True)
    started_at = _utc_now()
    manifest_data = load_manifest(plan.benchmark_id)
    skill_modes_config = manifest_data["skill_modes"]

    attempts_path = out / "attempts.jsonl"
    requeued_if = 0
    if resume:
        existing_attempts = _load_existing_attempts(attempts_path)
        # IF is an infra/inconclusive verdict — the result contract is "retry,
        # never charge". A transient provider 429 or sim flake must not be baked
        # into a resumed run, so drop IF rows and re-attempt them. Rewrite the
        # file with only the kept rows so the re-run appends without colliding.
        existing_attempts, requeued_if = _drop_inconclusive_attempts(existing_attempts)
        if requeued_if:
            _rewrite_attempts(attempts_path, existing_attempts)
        mode = "a"
    else:
        existing_attempts = {}
        mode = "w"
    expected_keys = _expected_attempt_keys(plan, reps)
    completed_existing = sum(1 for key in expected_keys if key in existing_attempts)

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
        "publishability": _run_publishability(plan.publishable, allow_unpublishable, model),
        "report_if_threshold": REPORT_IF_THRESHOLD_DEFAULT,
        "status": "running",
        "started_at": started_at,
        "harness_git_sha": _git_sha(),
        "benchmark_harness_hash": benchmark_harness_hash(),
        "build_kinds": sorted({item.task.board_profile.build_kind for item in plan.tasks}),
        "tool_versions": _tool_versions_for_plan(plan),
        "manifest_lock_sha": _sha_if_exists(plan.benchmark_root / "manifest.yaml"),
        "upstream_lock_sha": upstream_lock_sha(plan.benchmark_root),
        "skills_lock_sha": skills_lock_sha(plan.benchmark_root),
        "selection_counts": plan.counts,
        "selected_tasks": [
            {
                "canonical_id": item.manifest.canonical_id,
                "local_task_id": item.task.task_id,
                "platform": item.task.platform,
                "level": item.task.level,
                "score_eligible": item.manifest.score_eligible,
                "publishable": item.publishable,
                "build_kind": item.task.board_profile.build_kind,
            }
            for item in plan.tasks
        ],
        "cli_args": _jsonable(cli_args or {}),
        "resume": resume,
        "force": force,
        "attempts_expected": len(expected_keys),
        "attempts_written": 0,
        "attempts_skipped": completed_existing,
        "attempts_missing": len(expected_keys) - completed_existing,
        "attempts_requeued_if": requeued_if,
    }
    _write_experiment(out, experiment)

    written = 0
    skipped = 0
    try:
        with attempts_path.open(mode, encoding="utf-8", newline="\n") as stream:
            for resolved in plan.tasks:
                for skill_mode in plan.skill_modes:
                    for rep_index in range(1, reps + 1):
                        key = _attempt_key(resolved.task.task_id, skill_mode, rep_index)
                        if key in existing_attempts:
                            skipped += 1
                            continue
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
                        written += 1
                        _update_attempt_counts(experiment, written=written, skipped=skipped, expected=len(expected_keys))
                        _write_experiment(out, experiment)
    except KeyboardInterrupt:
        _finalize_experiment(out, experiment, status="interrupted", written=written, skipped=skipped, expected=len(expected_keys))
        raise
    except Exception:
        _finalize_experiment(out, experiment, status="failed", written=written, skipped=skipped, expected=len(expected_keys))
        raise

    _finalize_experiment(out, experiment, status="complete", written=written, skipped=skipped, expected=len(expected_keys))
    reports = write_reports(out, if_threshold=REPORT_IF_THRESHOLD_DEFAULT)
    return {
        "run": str(out),
        "attempts": str(attempts_path),
        "attempts_written": written,
        "attempts_skipped": skipped,
        "attempts_missing": experiment["attempts_missing"],
        "reports": reports,
    }


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
    api_key_env: str | None,
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
    prompt, base_text, skill_text = compose_prompt(task, skills)
    base_prompt_chars = len(base_text)
    skill_prompt_chars = len(skill_text)
    base_input_tokens, skill_input_tokens, prompt_tokenizer = split_token_counts(base_text, skill_text)
    prompt_path = out / "prompts" / f"{slug}.md"
    prompt_path.write_text(prompt, encoding="utf-8", newline="\n")

    response_path = out / "responses" / f"{slug}.raw.json"
    try:
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
    except ProviderFailure as exc:
        response_path.write_text(json.dumps(exc.raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = result_payload(
            SIM_INFRA_FAIL,
            exc.reason,
            failure_stage="generation",
            failure_source=SOURCE_HARNESS,
        )
        return _attempt_row(
            out,
            resolved,
            model=model,
            skill_mode=skill_mode,
            skills=skills,
            rep_index=rep_index,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            seed=seed,
            base_prompt_chars=base_prompt_chars,
            skill_prompt_chars=skill_prompt_chars,
            base_input_tokens=base_input_tokens,
            skill_input_tokens=skill_input_tokens,
            prompt_tokenizer=prompt_tokenizer,
            usage=None,
            num_model_calls=exc.num_model_calls,
            latency_s=exc.latency_s,
            generation_retries=max(0, exc.num_model_calls - 1),
            if_retries_used=0,
            result=result,
            prompt_path=prompt_path,
            response_path=response_path,
            source_path=None,
            extraction_metadata={},
        )
    response_path.write_text(json.dumps(response.raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    source_dir = out / "sources" / slug
    extraction = extract_submission(task, response.text, source_dir)
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
    return _attempt_row(
        out,
        resolved,
        model=model,
        skill_mode=skill_mode,
        skills=skills,
        rep_index=rep_index,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
        base_prompt_chars=base_prompt_chars,
        skill_prompt_chars=skill_prompt_chars,
        base_input_tokens=base_input_tokens,
        skill_input_tokens=skill_input_tokens,
        prompt_tokenizer=prompt_tokenizer,
        usage=usage if usage else None,
        num_model_calls=response.num_model_calls,
        latency_s=response.latency_s,
        generation_retries=max(0, response.num_model_calls - 1),
        if_retries_used=if_retries_used,
        result=result,
        prompt_path=prompt_path,
        response_path=response_path,
        source_path=extraction.source_path,
        extraction_metadata=extraction.metadata,
    )


def _attempt_row(
    out: Path,
    resolved: ResolvedTask,
    *,
    model: str,
    skill_mode: str,
    skills: list[Any],
    rep_index: int,
    temperature: float,
    top_p: float,
    max_tokens: int,
    seed: int | None,
    base_prompt_chars: int,
    skill_prompt_chars: int,
    base_input_tokens: int | None,
    skill_input_tokens: int | None,
    prompt_tokenizer: str | None,
    usage: dict[str, Any] | None,
    num_model_calls: int,
    latency_s: float,
    generation_retries: int,
    if_retries_used: int,
    result: dict[str, Any],
    prompt_path: Path,
    response_path: Path,
    source_path: Path | None,
    extraction_metadata: dict[str, Any],
) -> dict[str, Any]:
    task = resolved.task
    usage = usage or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    total_tokens = usage.get("total_tokens")
    # Authoritative provider-reported usage (null when the provider omits it).
    usage_source = usage.get("usage_source") if usage else None
    reasoning_tokens = usage.get("reasoning_tokens")
    cached_input_tokens = usage.get("cached_input_tokens")
    provider_cost = usage.get("cost")
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
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_input_tokens": cached_input_tokens,
        "provider_cost": provider_cost,
        "usage_source": usage_source,
        # base/skill split is a local tiktoken preflight estimate (the provider
        # reports only the combined input total), labeled by prompt_tokenizer.
        "base_input_tokens": base_input_tokens,
        "skill_input_tokens": skill_input_tokens,
        "prompt_tokenizer": prompt_tokenizer,
        "base_prompt_chars": base_prompt_chars,
        "skill_prompt_chars": skill_prompt_chars,
        "num_model_calls": num_model_calls,
        "latency_s": latency_s,
        "generation_retries": generation_retries,
        "if_retries_used": if_retries_used,
        "result": result.get("result"),
        "classification": result.get("classification"),
        "failure_stage": result.get("failure_stage"),
        "failure_source": result.get("failure_source"),
        "reason": result.get("reason"),
        "metrics": result.get("metrics") or {},
        "prompt_path": _rel(prompt_path, out),
        "response_path": _rel(response_path, out),
        "source_path": _rel(source_path, out) if source_path else "",
        "extraction": extraction_metadata,
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


def _tool_versions_for_plan(plan: PlanResult) -> dict[str, Any]:
    return {
        build_kind: current_tool_versions(build_kind=build_kind)
        for build_kind in sorted({item.task.board_profile.build_kind for item in plan.tasks})
    }


def _load_existing_attempts(path: Path) -> dict[tuple[str, str, int], dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[tuple[str, str, int], dict[str, Any]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}: malformed JSONL at line {line_no}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ConfigError(f"{path}: attempt line {line_no} must be a JSON object")
        missing = [field for field in ATTEMPT_KEY_FIELDS if field not in row]
        if missing:
            raise ConfigError(f"{path}: attempt line {line_no} missing required field(s): {', '.join(missing)}")
        try:
            key = _attempt_key(str(row["local_task_id"]), str(row["skill_mode"]), int(row["rep_index"]))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{path}: attempt line {line_no} has invalid rep_index") from exc
        if key in rows:
            raise ConfigError(
                f"{path}: duplicate attempt row for local_task_id={key[0]!r}, "
                f"skill_mode={key[1]!r}, rep_index={key[2]}"
            )
        rows[key] = row
    return rows


def _drop_inconclusive_attempts(
    attempts: dict[tuple[str, str, int], dict[str, Any]]
) -> tuple[dict[tuple[str, str, int], dict[str, Any]], int]:
    """Keep only conclusive attempts (BC/BF/CF); requeue IF for a re-attempt.

    Returns the retained attempts plus the count of IF rows dropped.
    """
    kept = {key: row for key, row in attempts.items() if row.get("result") != "IF"}
    return kept, len(attempts) - len(kept)


def _rewrite_attempts(path: Path, attempts: dict[tuple[str, str, int], dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in attempts.values():
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()


def _attempt_key(task_id: str, skill_mode: str, rep_index: int) -> tuple[str, str, int]:
    return (task_id, skill_mode, rep_index)


def _expected_attempt_keys(plan: PlanResult, reps: int) -> list[tuple[str, str, int]]:
    return [
        _attempt_key(resolved.task.task_id, skill_mode, rep_index)
        for resolved in plan.tasks
        for skill_mode in plan.skill_modes
        for rep_index in range(1, reps + 1)
    ]


def _clear_owned_run_outputs(out: Path) -> None:
    if not out.exists():
        return
    for name in OWNED_RUN_CHILDREN:
        child = out / name
        if child.is_dir():
            _remove_owned_tree(child)
        elif child.exists():
            child.unlink()


def _remove_owned_tree(path: Path) -> None:
    target = _filesystem_path(path)
    for attempt in range(5):
        try:
            shutil.rmtree(target, onexc=_ignore_missing_during_rmtree)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.1)


def _ignore_missing_during_rmtree(function: Any, path: str, excinfo: BaseException) -> None:
    if isinstance(excinfo, FileNotFoundError):
        return
    raise excinfo


def _filesystem_path(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def _write_experiment(out: Path, experiment: dict[str, Any]) -> None:
    (out / "experiment.json").write_text(json.dumps(experiment, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _update_attempt_counts(experiment: dict[str, Any], *, written: int, skipped: int, expected: int) -> None:
    experiment["attempts_written"] = written
    experiment["attempts_skipped"] = skipped
    experiment["attempts_missing"] = max(0, expected - written - skipped)


def _finalize_experiment(
    out: Path,
    experiment: dict[str, Any],
    *,
    status: str,
    written: int,
    skipped: int,
    expected: int,
) -> None:
    experiment["status"] = status
    experiment["ended_at"] = _utc_now()
    _update_attempt_counts(experiment, written=written, skipped=skipped, expected=expected)
    _write_experiment(out, experiment)


def _run_publishability(plan_publishable: bool, allow_unpublishable: bool, model: str) -> str:
    if model.startswith("fixture:"):
        return "local_smoke"
    if allow_unpublishable or not plan_publishable:
        return "unpublishable_override"
    return "publishable"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    return value


def _sha_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    return path.relative_to(root).as_posix()

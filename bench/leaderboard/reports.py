from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_IF_THRESHOLD = 0.05


def load_attempts(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "attempts.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"attempts file not found: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_reports(run_dir: Path, *, if_threshold: float = DEFAULT_IF_THRESHOLD) -> dict[str, str]:
    attempts = load_attempts(run_dir)
    experiment = load_experiment(run_dir)
    summaries = summarize_attempts(attempts, experiment=experiment, if_threshold=if_threshold)
    return _emit_reports(run_dir / "reports", attempts, summaries)


def aggregate_runs(
    run_dirs: list[Path], out_dir: Path, *, if_threshold: float = DEFAULT_IF_THRESHOLD
) -> dict[str, str]:
    """Merge several run directories into one combined leaderboard.

    Concatenates each run's `attempts.jsonl` and re-aggregates them so models
    appear as rows in a single table. Coverage is exact when the runs share the
    same task set and reps (the usual same-benchmark, different-model compare).
    """

    if not run_dirs:
        raise ValueError("aggregate_runs requires at least one run directory")
    attempts: list[dict[str, Any]] = []
    experiments: list[dict[str, Any]] = []
    sources: list[str] = []
    for run_dir in run_dirs:
        attempts.extend(load_attempts(run_dir))
        experiment = load_experiment(run_dir)
        if experiment is not None:
            experiments.append(experiment)
        sources.append(run_dir.name)
    merged_experiment = _merge_experiments(experiments)
    summaries = summarize_attempts(attempts, experiment=merged_experiment, if_threshold=if_threshold)
    summaries["metadata"]["aggregated_runs"] = sources
    paths = _emit_reports(out_dir, attempts, summaries)
    aggregate_json = out_dir / "aggregate.json"
    aggregate_json.write_text(
        json.dumps({"runs": sources, "attempts": len(attempts)}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["aggregate_json"] = str(aggregate_json)
    return paths


def _emit_reports(
    reports_dir: Path, attempts: list[dict[str, Any]], summaries: dict[str, Any]
) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)

    summary_json = reports_dir / "summary.json"
    summary_json.write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_csv = reports_dir / "summary.csv"
    _write_summary_csv(summary_csv, summaries["cells"])

    leaderboard_md = reports_dir / "leaderboard.md"
    leaderboard_md.write_text(_leaderboard_md(summaries), encoding="utf-8")

    failures_md = reports_dir / "failures.md"
    failures_md.write_text(_failures_md(attempts), encoding="utf-8")

    pareto_csv = reports_dir / "pareto.csv"
    _write_pareto_csv(pareto_csv, summaries["headline"])

    return {
        "summary_json": str(summary_json),
        "summary_csv": str(summary_csv),
        "leaderboard_md": str(leaderboard_md),
        "failures_md": str(failures_md),
        "pareto_csv": str(pareto_csv),
    }


def _merge_experiments(experiments: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not experiments:
        return None
    selected: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    reps_values: set[int] = set()
    for experiment in experiments:
        for task in experiment.get("selected_tasks") or []:
            if not isinstance(task, dict):
                continue
            key = (task.get("platform"), task.get("level"), task.get("local_task_id"))
            selected[key] = task
        reps = experiment.get("reps")
        if reps is not None:
            reps_values.add(int(reps))
    merged: dict[str, Any] = {"selected_tasks": list(selected.values())}
    # Only assert a shared reps count when every run agrees; otherwise leave it
    # unset so the coverage denominator falls back rather than miscounting.
    if len(reps_values) == 1:
        merged["reps"] = reps_values.pop()
    return merged


def load_experiment(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "experiment.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_attempts(
    attempts: list[dict[str, Any]],
    experiment: dict[str, Any] | None = None,
    *,
    if_threshold: float = DEFAULT_IF_THRESHOLD,
) -> dict[str, Any]:
    cells = []
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    headline_grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in attempts:
        grouped[(row["model"], row["platform"], row["level"], row["skill_mode"])].append(row)
        headline_grouped[(row["model"], row["skill_mode"])].append(row)

    for key, rows in sorted(grouped.items()):
        cells.append(_metrics_for_rows(rows, key, experiment=experiment))
    headline = [
        _metrics_for_rows(rows, (model, "all", "all", skill_mode), experiment=experiment)
        for (model, skill_mode), rows in sorted(headline_grouped.items())
    ]
    skill_lift = _skill_lift(headline)
    publishability = _publishability_status(headline, experiment=experiment, if_threshold=if_threshold)
    return {
        "metadata": {
            "if_threshold": if_threshold,
            "publishability": publishability,
            "attempts": len(attempts),
        },
        "cells": cells,
        "headline": headline,
        "skill_lift": skill_lift,
    }


def _metrics_for_rows(
    rows: list[dict[str, Any]],
    key: tuple[str, str, str, str],
    *,
    experiment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model, platform, level, skill_mode = key
    attempted = len(rows)
    bc = sum(1 for row in rows if row["result"] == "BC")
    bf = sum(1 for row in rows if row["result"] == "BF")
    cf = sum(1 for row in rows if row["result"] == "CF")
    iff = sum(1 for row in rows if row["result"] == "IF")
    scored = bc + bf + cf
    task_rep_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        task_rep_groups[(row["canonical_id"], row["skill_mode"])].append(row)
    pass_at_k = (
        sum(1 for group in task_rep_groups.values() if any(row["result"] == "BC" for row in group))
        / len(task_rep_groups)
        if task_rep_groups
        else 0.0
    )
    tokens = [row.get("total_tokens") for row in rows if row.get("total_tokens") is not None]
    input_tokens = [row.get("input_tokens") for row in rows if row.get("input_tokens") is not None]
    skill_input_tokens = [
        row.get("skill_input_tokens") for row in rows if row.get("skill_input_tokens") is not None
    ]
    base_chars = [row.get("base_prompt_chars") for row in rows if row.get("base_prompt_chars") is not None]
    skill_chars = [row.get("skill_prompt_chars") for row in rows if row.get("skill_prompt_chars") is not None]
    total_chars = [
        float(row.get("base_prompt_chars", 0)) + float(row.get("skill_prompt_chars", 0))
        for row in rows
        if row.get("base_prompt_chars") is not None or row.get("skill_prompt_chars") is not None
    ]
    denominator = _coverage_denominator(rows, platform=platform, level=level, experiment=experiment)
    return {
        "model": model,
        "platform": platform,
        "level": level,
        "skill_mode": skill_mode,
        "attempted": attempted,
        "bc": bc,
        "bf": bf,
        "cf": cf,
        "if": iff,
        "pass_at_1": round(bc / attempted, 6) if attempted else 0.0,
        "pass_at_k": round(pass_at_k, 6),
        "pass_rate_scored": round(bc / scored, 6) if scored else None,
        "coverage_rate": round(scored / denominator, 6) if denominator else 0.0,
        "coverage_denominator": denominator,
        "if_rate": round(iff / attempted, 6) if attempted else 0.0,
        "bc_pct": round(bc / attempted, 6) if attempted else 0.0,
        "cf_pct": round(cf / attempted, 6) if attempted else 0.0,
        "bf_pct": round(bf / attempted, 6) if attempted else 0.0,
        "if_pct": round(iff / attempted, 6) if attempted else 0.0,
        "tokens_per_task": round(sum(float(value) for value in tokens) / len(tokens), 3) if tokens else None,
        "input_tokens_per_task": round(sum(float(value) for value in input_tokens) / len(input_tokens), 3)
        if input_tokens
        else None,
        "skill_input_tokens_per_task": round(
            sum(float(value) for value in skill_input_tokens) / len(skill_input_tokens), 3
        )
        if skill_input_tokens
        else None,
        "base_prompt_chars": round(sum(float(value) for value in base_chars) / len(base_chars), 3) if base_chars else None,
        "skill_prompt_chars": round(sum(float(value) for value in skill_chars) / len(skill_chars), 3) if skill_chars else None,
        "total_prompt_chars": round(sum(total_chars) / len(total_chars), 3) if total_chars else None,
        "tokens_per_pass": round(sum(float(value) for value in tokens) / bc, 3) if tokens and bc else None,
    }


def _coverage_denominator(
    rows: list[dict[str, Any]],
    *,
    platform: str,
    level: str,
    experiment: dict[str, Any] | None,
) -> int:
    if experiment:
        tasks = experiment.get("selected_tasks")
        reps = int(experiment.get("reps") or 1)
        if isinstance(tasks, list):
            eligible = 0
            for task in tasks:
                if not isinstance(task, dict) or not task.get("score_eligible", True):
                    continue
                if platform != "all" and task.get("platform") != platform:
                    continue
                if level != "all" and task.get("level") != level:
                    continue
                eligible += 1
            if eligible:
                return eligible * reps
        counts = experiment.get("selection_counts")
        if platform == "all" and level == "all" and isinstance(counts, dict):
            denominator = counts.get("score_eligible_generations")
            if isinstance(denominator, int):
                return denominator
    return len(rows)


def _skill_lift(headline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = {
        row["model"]: row
        for row in headline
        if row["skill_mode"] == "none"
    }
    rows = []
    for row in headline:
        if row["skill_mode"] == "none" or row["model"] not in baseline:
            continue
        base = baseline[row["model"]]
        delta_pass = round(row["pass_at_1"] - base["pass_at_1"], 6)
        delta_tokens = _nullable_delta(
            row.get("input_tokens_per_task"), base.get("input_tokens_per_task")
        )
        # Token-based ROI activates only when a tokenizer populated the split;
        # the char-based ROI is the always-available fallback (chars are exact).
        lift_per_1k = _lift_per_1k(delta_pass, row.get("skill_input_tokens_per_task"))
        lift_per_1k_chars = _lift_per_1k(delta_pass, row.get("skill_prompt_chars"))
        rows.append(
            {
                "model": row["model"],
                "skill_mode": row["skill_mode"],
                "delta_pass_at_1": delta_pass,
                "delta_input_tokens": delta_tokens,
                "lift_per_1k_skill_tokens": lift_per_1k,
                "lift_per_1k_skill_chars": lift_per_1k_chars,
            }
        )
    return rows


def _lift_per_1k(delta_pass: float, denominator: Any) -> float | None:
    if denominator in (None, 0):
        return None
    return round(delta_pass / float(denominator) * 1000, 6)


def _nullable_delta(value: Any, base: Any) -> float | None:
    if value is None or base is None:
        return None
    return round(float(value) - float(base), 6)


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "model",
        "platform",
        "level",
        "skill_mode",
        "attempted",
        "bc",
        "bf",
        "cf",
        "if",
        "pass_at_1",
        "pass_at_k",
        "pass_rate_scored",
        "coverage_rate",
        "coverage_denominator",
        "if_rate",
        "bc_pct",
        "cf_pct",
        "bf_pct",
        "if_pct",
        "tokens_per_task",
        "input_tokens_per_task",
        "skill_input_tokens_per_task",
        "base_prompt_chars",
        "skill_prompt_chars",
        "total_prompt_chars",
        "tokens_per_pass",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _leaderboard_md(summary: dict[str, Any]) -> str:
    lines = ["# IoT-Bench Leaderboard Run", ""]
    metadata = summary.get("metadata") or {}
    lines.append(f"Publishability: `{metadata.get('publishability')}`")
    lines.append(f"IF threshold: `{metadata.get('if_threshold')}`")
    lines.append("")
    lines.append("## Table 1 - Headline")
    lines.append("| model | skill_mode | pass@1 | pass@k | scored pass | coverage | BC% | CF% | BF% | IF% | tokens/task | prompt chars | tokens/pass |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in summary["headline"]:
        lines.append(
            "| {model} | {skill_mode} | {pass_at_1} | {pass_at_k} | {pass_rate_scored} | {coverage_rate} | {bc_pct} | {cf_pct} | {bf_pct} | {if_pct} | {tokens_per_task} | {total_prompt_chars} | {tokens_per_pass} |".format(
                **row
            )
        )
    lines.extend(["", "## Table 2 - Skill Lift", ""])
    lines.append("| model | skill_mode | delta pass@1 | delta input tokens | lift /1k skill-tok | lift /1k skill-char |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in summary["skill_lift"]:
        lines.append(
            "| {model} | {skill_mode} | {delta_pass_at_1} | {delta_input_tokens} | {lift_per_1k_skill_tokens} | {lift_per_1k_skill_chars} |".format(
                **row
            )
        )
    lines.extend(["", "## Table 3 - By Level", ""])
    lines.append("| model | skill_mode | level | pass@1 |")
    lines.append("|---|---|---:|---:|")
    for row in summary["cells"]:
        lines.append(f"| {row['model']} | {row['skill_mode']} | {row['level']} | {row['pass_at_1']} |")
    return "\n".join(lines) + "\n"


def _publishability_status(
    headline: list[dict[str, Any]],
    *,
    experiment: dict[str, Any] | None,
    if_threshold: float,
) -> str:
    if any(float(row.get("if_rate") or 0.0) > if_threshold for row in headline):
        return "high_if_rate"
    if experiment:
        current = experiment.get("publishability")
        if current in {"local_smoke", "publishable", "unpublishable_override"}:
            return str(current)
        if experiment.get("allow_unpublishable") or not experiment.get("publishable", True):
            return "unpublishable_override"
    return "publishable"


def _failures_md(attempts: list[dict[str, Any]]) -> str:
    failures = [row for row in attempts if row["result"] != "BC"]
    by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in failures:
        by_stage[str(row.get("failure_stage") or "unknown")].append(row)
    lines = ["# Failures", ""]
    if not failures:
        lines.append("No failures.")
        return "\n".join(lines) + "\n"
    for stage, rows in sorted(by_stage.items()):
        lines.extend([f"## {stage}", ""])
        for row in rows:
            lines.append(
                f"- `{row['local_task_id']}` `{row['skill_mode']}` rep {row['rep_index']}: "
                f"{row['result']} {row.get('reason') or ''} "
                f"([prompt]({row['prompt_path']}), [response]({row['response_path']}), [source]({row['source_path']}))"
            )
        lines.append("")
    return "\n".join(lines)


def _write_pareto_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    pareto_rows = _mark_pareto(rows)
    fields = ["model", "skill_mode", "tokens_per_task", "pass_at_1", "on_frontier"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(pareto_rows)


def _mark_pareto(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    comparable = [row for row in rows if row.get("tokens_per_task") is not None]
    for row in rows:
        dominated = False
        if row.get("tokens_per_task") is not None:
            for other in comparable:
                if other is row:
                    continue
                if (
                    other["tokens_per_task"] <= row["tokens_per_task"]
                    and other["pass_at_1"] >= row["pass_at_1"]
                    and (other["tokens_per_task"] < row["tokens_per_task"] or other["pass_at_1"] > row["pass_at_1"])
                ):
                    dominated = True
                    break
        output.append(
            {
                "model": row["model"],
                "skill_mode": row["skill_mode"],
                "tokens_per_task": row.get("tokens_per_task"),
                "pass_at_1": row["pass_at_1"],
                "on_frontier": not dominated if row.get("tokens_per_task") is not None else "",
            }
        )
    return output

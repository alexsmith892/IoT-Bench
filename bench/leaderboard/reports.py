from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_attempts(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "attempts.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"attempts file not found: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_reports(run_dir: Path) -> dict[str, str]:
    attempts = load_attempts(run_dir)
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summaries = summarize_attempts(attempts)

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


def summarize_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    cells = []
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    headline_grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in attempts:
        grouped[(row["model"], row["platform"], row["level"], row["skill_mode"])].append(row)
        headline_grouped[(row["model"], row["skill_mode"])].append(row)

    for key, rows in sorted(grouped.items()):
        cells.append(_metrics_for_rows(rows, key))
    headline = [
        _metrics_for_rows(rows, (model, "all", "all", skill_mode))
        for (model, skill_mode), rows in sorted(headline_grouped.items())
    ]
    skill_lift = _skill_lift(headline)
    return {"cells": cells, "headline": headline, "skill_lift": skill_lift}


def _metrics_for_rows(rows: list[dict[str, Any]], key: tuple[str, str, str, str]) -> dict[str, Any]:
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
    costs = [row.get("cost_usd") for row in rows if row.get("cost_usd") is not None]
    tokens = [row.get("total_tokens") for row in rows if row.get("total_tokens") is not None]
    cost_sum = sum(float(value) for value in costs)
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
        "coverage_rate": round(scored / attempted, 6) if attempted else 0.0,
        "if_rate": round(iff / attempted, 6) if attempted else 0.0,
        "cf_pct": round(cf / attempted, 6) if attempted else 0.0,
        "bf_pct": round(bf / attempted, 6) if attempted else 0.0,
        "if_pct": round(iff / attempted, 6) if attempted else 0.0,
        "tokens_per_task": round(sum(float(value) for value in tokens) / len(tokens), 3) if tokens else None,
        "cost_per_task": round(cost_sum / len(costs), 8) if costs else None,
        "cost_per_pass": round(cost_sum / bc, 8) if costs and bc else None,
    }


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
        delta_cost = _nullable_delta(row.get("cost_per_task"), base.get("cost_per_task"))
        delta_tokens = _nullable_delta(row.get("tokens_per_task"), base.get("tokens_per_task"))
        rows.append(
            {
                "model": row["model"],
                "skill_mode": row["skill_mode"],
                "delta_pass_at_1": round(row["pass_at_1"] - base["pass_at_1"], 6),
                "delta_input_tokens": delta_tokens,
                "delta_cost_per_task": delta_cost,
                "lift_per_1k_skill_tokens": None,
            }
        )
    return rows


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
        "coverage_rate",
        "if_rate",
        "tokens_per_task",
        "cost_per_task",
        "cost_per_pass",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _leaderboard_md(summary: dict[str, Any]) -> str:
    lines = ["# IoT-Bench Leaderboard Run", ""]
    lines.append("## Table 1 - Headline")
    lines.append("| model | skill_mode | pass@1 | pass@k | coverage | CF% | BF% | IF% | tokens/task | cost/task | cost/pass |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in summary["headline"]:
        lines.append(
            "| {model} | {skill_mode} | {pass_at_1} | {pass_at_k} | {coverage_rate} | {cf_pct} | {bf_pct} | {if_pct} | {tokens_per_task} | {cost_per_task} | {cost_per_pass} |".format(
                **row
            )
        )
    lines.extend(["", "## Table 2 - Skill Lift", ""])
    lines.append("| model | skill_mode | delta pass@1 | delta input tokens | delta cost/task | lift /1k skill-tok |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in summary["skill_lift"]:
        lines.append(
            "| {model} | {skill_mode} | {delta_pass_at_1} | {delta_input_tokens} | {delta_cost_per_task} | {lift_per_1k_skill_tokens} |".format(
                **row
            )
        )
    lines.extend(["", "## Table 3 - By Level", ""])
    lines.append("| model | skill_mode | level | pass@1 |")
    lines.append("|---|---|---:|---:|")
    for row in summary["cells"]:
        lines.append(f"| {row['model']} | {row['skill_mode']} | {row['level']} | {row['pass_at_1']} |")
    return "\n".join(lines) + "\n"


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
    fields = ["model", "skill_mode", "cost_per_task", "pass_at_1", "on_frontier"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(pareto_rows)


def _mark_pareto(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    comparable = [row for row in rows if row.get("cost_per_task") is not None]
    for row in rows:
        dominated = False
        if row.get("cost_per_task") is not None:
            for other in comparable:
                if other is row:
                    continue
                if (
                    other["cost_per_task"] <= row["cost_per_task"]
                    and other["pass_at_1"] >= row["pass_at_1"]
                    and (other["cost_per_task"] < row["cost_per_task"] or other["pass_at_1"] > row["pass_at_1"])
                ):
                    dominated = True
                    break
        output.append(
            {
                "model": row["model"],
                "skill_mode": row["skill_mode"],
                "cost_per_task": row.get("cost_per_task"),
                "pass_at_1": row["pass_at_1"],
                "on_frontier": not dominated if row.get("cost_per_task") is not None else "",
            }
        )
    return output


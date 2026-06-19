"""Render the leaderboard figures (pass rate + token usage) from a run.

These reproduce the two upstream paper plots — "pass rates across platforms,
skills configurations, and task difficulty levels" and "average per-task token
usage" — directly from one or more run directories' ``attempts.jsonl``.

The paper's pass-rate figure aggregates over difficulty levels; here we add a
per-level breakdown (one panel per ``level1/2/3``) on top of the aggregate
panel, so the same data answers both "how does each MCU do overall" and "how
does difficulty bite". Everything is computed from raw attempts, so it works on
a single-platform run, a multi-skill run, or an aggregated cross-platform one.

CLI: ``python -m bench.leaderboard charts --run <run_dir> [--out <dir>]``
(``--run`` accepts several dirs and merges them, the same way ``aggregate``
does — handy for stitching the three single-platform sweeps into one figure).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .reports import load_attempts

# --- Fixed presentation order + labels -------------------------------------
# Platform order and two-line labels mirror the paper's x-axis (MCU + stack).
PLATFORMS: tuple[tuple[str, str], ...] = (
    ("arduino_mega", "ATmega2560\n+ Arduino"),
    ("zephyr_nano33ble", "nRF52840\n+ Zephyr"),
    ("esp32s3_espidf", "ESP32-S3\n+ ESP-IDF"),
)
# Skill mode order + label + (dark, light) shade. Dark = Pass@1 / input tokens,
# light = Pass@k / output tokens — the same dark-over-light overlay the paper uses.
SKILL_MODES: tuple[tuple[str, str, str, str], ...] = (
    ("none", "No-Skills", "#3a78b5", "#bcd6ec"),
    ("llm_generated", "LLM-Generated", "#c43d3d", "#f1b9b9"),
    ("human_expert", "Human-Expert", "#4f9e4f", "#bfe0bf"),
)
LEVELS: tuple[str, ...] = ("level1", "level2", "level3")


def _aggregate(attempts: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Reduce raw attempts to one metrics dict per (platform, level, skill_mode).

    ``level`` is replaced by the sentinel ``"all"`` cell in addition to the real
    per-level cells, so callers can render both the aggregate and the breakdown
    from one pass.
    """

    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in attempts:
        platform = row.get("platform")
        skill_mode = row.get("skill_mode")
        level = row.get("level")
        if platform is None or skill_mode is None:
            continue
        buckets[(platform, level, skill_mode)].append(row)
        buckets[(platform, "all", skill_mode)].append(row)

    return {key: _metrics(rows) for key, rows in buckets.items()}


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = len(rows)
    bc = sum(1 for row in rows if row.get("result") == "BC")

    # pass@k: group reps by (platform, canonical_id, skill_mode); a task passes
    # if any rep is BC. k is the reps-per-task this pass@k summarizes. This is
    # the same grouping reports.py uses, so the numbers line up with summary.json.
    rep_groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rep_groups[(row.get("platform"), row.get("canonical_id"), row.get("skill_mode"))].append(row)
    pass_at_k = (
        sum(1 for g in rep_groups.values() if any(r.get("result") == "BC" for r in g)) / len(rep_groups)
        if rep_groups
        else 0.0
    )
    k = max((len(g) for g in rep_groups.values()), default=0)

    inp = [r["input_tokens"] for r in rows if r.get("input_tokens") is not None]
    out = [r["output_tokens"] for r in rows if r.get("output_tokens") is not None]
    return {
        "attempted": attempted,
        "bc": bc,
        "pass_at_1": bc / attempted if attempted else 0.0,
        "pass_at_k": pass_at_k,
        "k": k,
        "input_tokens": sum(inp) / len(inp) if inp else None,
        "output_tokens": sum(out) / len(out) if out else None,
    }


def _present_levels(data: dict[tuple[str, str, str], dict[str, Any]]) -> list[str]:
    seen = {level for (_, level, _) in data}
    return [lvl for lvl in LEVELS if lvl in seen]


def _max_k(data: dict[tuple[str, str, str], dict[str, Any]]) -> int:
    return max((cell["k"] for cell in data.values()), default=1)


# --- Rendering --------------------------------------------------------------


def _draw_pass_panel(ax, data, level: str, k: int) -> None:
    import numpy as np

    n_platforms = len(PLATFORMS)
    n_skills = len(SKILL_MODES)
    group_width = 0.8
    bar_width = group_width / n_skills
    x = np.arange(n_platforms)

    for s_idx, (mode, _label, dark, light) in enumerate(SKILL_MODES):
        offset = (s_idx - (n_skills - 1) / 2) * bar_width
        for p_idx, (platform, _plabel) in enumerate(PLATFORMS):
            cell = data.get((platform, level, mode))
            if cell is None or cell["attempted"] == 0:
                continue
            pos = x[p_idx] + offset
            # Light Pass@k drawn full-height first, dark Pass@1 overlaid on top.
            ax.bar(pos, cell["pass_at_k"] * 100, bar_width, color=light, edgecolor="white", linewidth=0.4)
            ax.bar(pos, cell["pass_at_1"] * 100, bar_width, color=dark, edgecolor="white", linewidth=0.4)

    ax.set_xticks(x)
    ax.set_xticklabels([label for _, label in PLATFORMS], fontsize=8)
    ax.set_ylim(0, 105)
    ax.set_yticks(range(0, 101, 20))
    ax.set_yticklabels([f"{v}%" for v in range(0, 101, 20)], fontsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax.set_axisbelow(True)
    title = "All levels" if level == "all" else level.replace("level", "Level ")
    ax.set_title(title, fontsize=10)


def render_pass_rate(data, out_path: Path) -> Path:
    """Pass@1 / Pass@k overlay bars: one aggregate panel + one panel per level."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt

    k = _max_k(data)
    levels = ["all", *_present_levels(data)]
    fig, axes = plt.subplots(1, len(levels), figsize=(4.6 * len(levels), 4.4), sharey=True)
    if len(levels) == 1:
        axes = [axes]
    for ax, level in zip(axes, levels):
        _draw_pass_panel(ax, data, level, k)
    axes[0].set_ylabel("Pass Rate", fontsize=10)

    handles = []
    for _mode, label, dark, light in SKILL_MODES:
        # With reps=1 Pass@k == Pass@1 (no overlay), so drop the redundant row.
        if k > 1:
            handles.append(mpatches.Patch(color=light, label=f"{label} - Pass@{k}"))
        handles.append(mpatches.Patch(color=dark, label=f"{label} - Pass@1"))
    fig.legend(handles=handles, ncol=3, loc="upper center", fontsize=8, frameon=False, bbox_to_anchor=(0.5, 1.02))
    fig.suptitle(
        "Pass rates across platforms, skill configurations, and difficulty levels",
        fontsize=11,
        y=-0.02,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.93))
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def render_token_usage(data, out_path: Path, *, level: str = "all") -> Path:
    """Per-task input (dark, bottom) + output (light, stacked) tokens by platform/skill."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import numpy as np

    n_platforms = len(PLATFORMS)
    n_skills = len(SKILL_MODES)
    group_width = 0.8
    bar_width = group_width / n_skills
    x = np.arange(n_platforms)

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for s_idx, (mode, _label, dark, light) in enumerate(SKILL_MODES):
        offset = (s_idx - (n_skills - 1) / 2) * bar_width
        for p_idx, (platform, _plabel) in enumerate(PLATFORMS):
            cell = data.get((platform, level, mode))
            if cell is None or cell["input_tokens"] is None:
                continue
            pos = x[p_idx] + offset
            inp = cell["input_tokens"]
            out = cell["output_tokens"] or 0
            ax.bar(pos, inp, bar_width, color=dark, edgecolor="white", linewidth=0.4)
            ax.bar(pos, out, bar_width, bottom=inp, color=light, edgecolor="white", linewidth=0.4)

    ax.set_xticks(x)
    ax.set_xticklabels([label for _, label in PLATFORMS], fontsize=9)
    ax.set_ylabel("Average Token Usage Per Task", fontsize=10)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax.set_axisbelow(True)
    ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v):,}"))

    handles = []
    for _mode, label, dark, light in SKILL_MODES:
        handles.append(mpatches.Patch(color=dark, label=f"{label} - Input"))
        handles.append(mpatches.Patch(color=light, label=f"{label} - Output"))
    ax.legend(handles=handles, ncol=3, loc="upper center", fontsize=8, frameon=False, bbox_to_anchor=(0.5, 1.13))
    suffix = "" if level == "all" else f" ({level})"
    fig.suptitle(f"Average per-task token usage across platforms and skill configurations{suffix}", fontsize=11, y=-0.01)
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def write_charts(run_dirs: list[Path], out_dir: Path) -> dict[str, str]:
    """Aggregate the given run dir(s) and render both figures into ``out_dir``."""

    if not run_dirs:
        raise ValueError("write_charts requires at least one run directory")
    try:
        import matplotlib  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "matplotlib is required for `leaderboard charts`; install it with "
            "`pip install matplotlib` (it is an optional requirement)."
        ) from exc
    attempts: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        attempts.extend(load_attempts(run_dir))
    data = _aggregate(attempts)
    out_dir.mkdir(parents=True, exist_ok=True)
    pass_png = render_pass_rate(data, out_dir / "pass_rate.png")
    token_png = render_token_usage(data, out_dir / "token_usage.png")
    return {"pass_rate_png": str(pass_png), "token_usage_png": str(token_png)}

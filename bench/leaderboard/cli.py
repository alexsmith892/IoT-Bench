from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bench.config import ConfigError
from bench.results import SIM_INFRA_FAIL, SOURCE_HARNESS, emit_result

from .manifest import plan_payload, resolve_plan
from .reports import write_reports
from .run import run_experiment


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="IoT-Bench leaderboard orchestration")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="validate and enumerate a leaderboard run without spend")
    _add_selection_args(plan)

    run = sub.add_parser("run", help="run a leaderboard experiment")
    _add_selection_args(run)
    run.add_argument("--model", required=True)
    run.add_argument("--api-base")
    run.add_argument("--api-key-env", default="OPENAI_API_KEY")
    run.add_argument("--reps", type=int, default=1)
    run.add_argument("--temperature", type=float, default=0.2)
    run.add_argument("--top-p", type=float, default=1.0)
    run.add_argument("--max-tokens", type=int, default=4096)
    run.add_argument("--seed", type=int)
    run.add_argument("--if-retries", type=int, default=1)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--confirm-spend", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--force", action="store_true")
    run.add_argument("--max-generations", type=int)
    run.add_argument("--simulation-time-ms", type=int)
    run.add_argument("--allow-tool-version-mismatch", action="store_true")

    report = sub.add_parser("report", help="regenerate reports for an existing run")
    report.add_argument("--run", type=Path, required=True)
    return parser.parse_args(argv)


def _add_selection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--platform", default="arduino_mega")
    parser.add_argument("--levels", default="1,2,3")
    parser.add_argument("--skill-modes", default="none,llm_generated,human_expert")
    parser.add_argument("--tasks")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-unpublishable", action="store_true")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "plan":
            plan = resolve_plan(
                args.benchmark,
                platform=args.platform,
                levels=args.levels,
                skill_modes=args.skill_modes,
                task_ids=args.tasks,
                limit=args.limit,
                allow_unpublishable=args.allow_unpublishable,
            )
            print(json.dumps(plan_payload(plan), indent=2))
            return 0
        if args.command == "run":
            plan = resolve_plan(
                args.benchmark,
                platform=args.platform,
                levels=args.levels,
                skill_modes=args.skill_modes,
                task_ids=args.tasks,
                reps=args.reps,
                limit=args.limit,
                out=args.out,
                allow_unpublishable=args.allow_unpublishable,
            )
            result = run_experiment(
                plan,
                model=args.model,
                out=args.out,
                dry_run=args.dry_run,
                confirm_spend=args.confirm_spend,
                resume=args.resume,
                force=args.force,
                max_generations=args.max_generations,
                reps=args.reps,
                temperature=args.temperature,
                top_p=args.top_p,
                max_tokens=args.max_tokens,
                seed=args.seed,
                if_retries=args.if_retries,
                api_base=args.api_base,
                api_key_env=args.api_key_env,
                simulation_time_ms=args.simulation_time_ms,
                allow_tool_version_mismatch=args.allow_tool_version_mismatch,
                allow_unpublishable=args.allow_unpublishable,
                cli_args=vars(args),
            )
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "report":
            print(json.dumps(write_reports(args.run), indent=2))
            return 0
    except ConfigError as exc:
        return emit_result(SIM_INFRA_FAIL, str(exc), failure_source=SOURCE_HARNESS)
    return emit_result(SIM_INFRA_FAIL, f"unsupported command: {args.command}", failure_source=SOURCE_HARNESS)


if __name__ == "__main__":
    raise SystemExit(main())

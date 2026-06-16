"""Unified CLI for generating, running, and validating benchmark tasks."""

from __future__ import annotations

import argparse
import dataclasses
from datetime import datetime, timezone
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .config import ALL_LEVELS, ConfigError, board_profile_for_platform, iter_platform_tasks, iter_tasks, load_task
from .diagrams import DiagramError, validate_diagram_file
from .results import (
    FAIL,
    PASS,
    SIM_INFRA_FAIL,
    SIM_OUTPUT_FAIL,
    SOURCE_ARTIFACT,
    SOURCE_HARNESS,
    SOURCE_USER_CODE,
    emit_result,
    result_payload,
)
from .runner import (
    BuildSimulationError,
    CaseConfigError,
    CasePaths,
    build_case,
    command_with_windows_batch_wrapper,
    case_dir_for_task,
    ensure_tool_versions_compatible,
    expected_firmware_paths,
    generate_case,
    hash_file,
    hash_path,
    load_case_paths,
    normalize_sketch_override,
    prepare_artifacts,
    run_case,
    tool_version_report,
    parse_tool_version,
    validate_case,
    with_archived_vcd,
)
from .scenarios import ScenarioError
from .serial import SerialLogError
from .renode import RenodeConfigError
from . import renode as renode_module
from .validators import StaticCheckError, VcdParseError, validate_task


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="IoT-Bench Arduino task harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_task_selection(subparsers.add_parser("generate", help="generate case artifacts"))
    prompt = subparsers.add_parser("prompt", help="print the frozen model-facing task prompt")
    add_task_selection(prompt, require_task=True)

    build = subparsers.add_parser("build", help="compile sketches and verify firmware artifacts")
    add_task_selection(build)
    build.add_argument("--case", type=Path, help="case directory to build")
    build.add_argument("--sketch", type=Path, help="submitted sketch directory or .ino file")
    build.add_argument("--regenerate", action="store_true")
    build.add_argument("--arduino-cli", default="arduino-cli")
    build.add_argument("--idf-py", default="idf.py")
    build.add_argument("--west", default="west")

    add_task_selection(subparsers.add_parser("lint", help="locally lint generated diagrams"))
    doctor = subparsers.add_parser("doctor", help="check local benchmark tooling")
    doctor.add_argument("--platform", default="arduino_mega")

    run = subparsers.add_parser("run", help="run simulation and validate task artifacts")
    add_task_selection(run)
    add_run_options(run)

    evaluate = subparsers.add_parser("evaluate", help="batch-evaluate task submissions into JSONL")
    add_task_selection(evaluate, default_level="all")
    evaluate.add_argument("--sketch-dir", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--if-retries", type=int, default=1)
    evaluate.add_argument("--regenerate", action="store_true")
    evaluate.add_argument("--simulation-time-ms", type=int)
    evaluate.add_argument("--arduino-cli", default="arduino-cli")
    evaluate.add_argument("--idf-py", default="idf.py")
    evaluate.add_argument("--wokwi-cli", default="wokwi-cli")
    evaluate.add_argument("--west", default="west")
    evaluate.add_argument("--renode", default="renode")
    evaluate.add_argument("--allow-tool-version-mismatch", action="store_true")

    repeatability = subparsers.add_parser("repeatability", help="run reference sketches repeatedly and emit a flake census JSONL")
    add_task_selection(repeatability, default_level="all")
    repeatability.add_argument("--runs", type=int, required=True)
    repeatability.add_argument("--output", type=Path, required=True)
    repeatability.add_argument("--regenerate", action="store_true")
    repeatability.add_argument("--simulation-time-ms", type=int)
    repeatability.add_argument("--arduino-cli", default="arduino-cli")
    repeatability.add_argument("--idf-py", default="idf.py")
    repeatability.add_argument("--wokwi-cli", default="wokwi-cli")
    repeatability.add_argument("--west", default="west")
    repeatability.add_argument("--renode", default="renode")
    repeatability.add_argument("--allow-tool-version-mismatch", action="store_true")

    validate = subparsers.add_parser(
        "validate-artifacts", help="validate existing artifacts without running Wokwi"
    )
    add_task_selection(validate, require_task=True)
    validate.add_argument("--case", type=Path, help="case directory to validate")
    validate.add_argument("--sketch", type=Path, help="submitted sketch directory or .ino file")
    validate.add_argument("--archived-vcd", help="validate archived VCD by filename or 'latest'")
    validate.add_argument(
        "--allow-unverified-artifacts",
        action="store_true",
        help="skip verification.json provenance checks (deliberate inspection of arbitrary artifacts)",
    )
    validate.add_argument("--allow-tool-version-mismatch", action="store_true")

    return parser.parse_args(argv)


def add_task_selection(
    parser: argparse.ArgumentParser,
    *,
    require_task: bool = False,
    default_level: str = "level1",
) -> None:
    parser.add_argument("--task", required=require_task, help="task id, e.g. blink_led_1hz")
    parser.add_argument("--platform", default="arduino_mega")
    parser.add_argument("--level", default=default_level)


def add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--case", type=Path, help="case directory to run")
    parser.add_argument("--sketch", type=Path, help="submitted sketch directory or .ino file")
    parser.add_argument("--use-existing-artifacts", action="store_true")
    parser.add_argument(
        "--allow-unverified-artifacts",
        action="store_true",
        help="with --use-existing-artifacts, skip verification.json provenance checks",
    )
    parser.add_argument("--regenerate", action="store_true")
    parser.add_argument("--simulation-time-ms", type=int)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    parser.add_argument("--idf-py", default="idf.py")
    parser.add_argument("--wokwi-cli", default="wokwi-cli")
    parser.add_argument("--west", default="west")
    parser.add_argument("--renode", default="renode")
    parser.add_argument("--allow-tool-version-mismatch", action="store_true")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "generate":
            tasks = selected_tasks(args)
            generated = []
            unsupported = []
            for task in tasks:
                if not task.is_supported:
                    unsupported.append(unsupported_task_payload(task))
                    continue
                generated.append(str(generate_case(task).case_dir))
            print(json.dumps({"generated": generated, "unsupported": unsupported}, indent=2))
            return 0
        if args.command == "prompt":
            task = load_selected_task(args)
            print(task.prompt_text, end="")
            return 0
        if args.command == "build":
            tasks = selected_tasks(args)
            results = [
                build_single_task(
                    task,
                    case_dir=args.case,
                    sketch_override=args.sketch,
                    regenerate=args.regenerate,
                    arduino_cli=args.arduino_cli,
                    idf_py=args.idf_py,
                    west=args.west,
                )
                for task in tasks
            ]
            print_many_or_one(results)
            return 0
        if args.command == "lint":
            tasks = selected_tasks(args)
            linted = []
            unsupported = []
            for task in tasks:
                if not task.is_supported:
                    unsupported.append(unsupported_task_payload(task))
                    continue
                paths = ensure_case(task)
                lint_case_platform_file(task, paths)
                linted.append(str(paths.diagram))
            print(json.dumps({"linted": linted, "unsupported": unsupported}, indent=2))
            return 0
        if args.command == "doctor":
            print(json.dumps(run_doctor(platform=args.platform), indent=2))
            return 0
        if args.command == "validate-artifacts":
            task = load_task(args.task, platform=args.platform, level=args.level)
            result = run_single_task(
                task,
                case_dir=args.case,
                sketch_override=args.sketch,
                use_existing_artifacts=True,
                regenerate=False,
                simulation_time_ms=None,
                arduino_cli="arduino-cli",
                idf_py="idf.py",
                wokwi_cli="wokwi-cli",
                west="west",
                renode_cli="renode",
                archived_vcd=args.archived_vcd,
                require_provenance=not args.allow_unverified_artifacts,
                allow_tool_version_mismatch=args.allow_tool_version_mismatch,
            )
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "run":
            tasks = selected_tasks(args)
            results = [
                run_single_task(
                    task,
                    case_dir=args.case,
                    sketch_override=args.sketch,
                    use_existing_artifacts=args.use_existing_artifacts,
                    regenerate=args.regenerate,
                    simulation_time_ms=args.simulation_time_ms,
                    arduino_cli=args.arduino_cli,
                    idf_py=args.idf_py,
                    wokwi_cli=args.wokwi_cli,
                    west=args.west,
                    renode_cli=args.renode,
                    archived_vcd=None,
                    require_provenance=not args.allow_unverified_artifacts,
                    allow_tool_version_mismatch=args.allow_tool_version_mismatch,
                )
                for task in tasks
            ]
            print_many_or_one(results)
            return 0
        if args.command == "evaluate":
            payload = evaluate_submissions(args)
            print(json.dumps(payload, indent=2))
            return 0
        if args.command == "repeatability":
            payload = measure_repeatability(args)
            print(json.dumps(payload, indent=2))
            return 0
    except (ConfigError, CaseConfigError, DiagramError, ScenarioError, RenodeConfigError) as exc:
        return emit_result(SIM_INFRA_FAIL, str(exc), failure_source=SOURCE_HARNESS)

    return emit_result(FAIL, f"unsupported command: {args.command}", failure_source=SOURCE_HARNESS)


def selected_tasks(args: argparse.Namespace):
    if args.task:
        return [load_selected_task(args)]
    if args.level == "all":
        return list(iter_platform_tasks(platform=args.platform))
    return list(iter_tasks(platform=args.platform, level=args.level))


def load_selected_task(args: argparse.Namespace):
    if args.level != "all":
        return load_task(args.task, platform=args.platform, level=args.level)
    matches = [
        task
        for task in iter_platform_tasks(platform=args.platform)
        if task.task_id == args.task
    ]
    if not matches:
        raise ConfigError(f"task config not found for {args.platform}/{args.task} in levels {', '.join(ALL_LEVELS)}")
    if len(matches) > 1:
        raise ConfigError(f"task id {args.task!r} appears in multiple levels; pass --level explicitly")
    return matches[0]


def ensure_case(task):
    case_dir = case_dir_for_task(task)
    if not (case_dir / "case.yaml").exists() and not (case_dir / "case.json").exists():
        return generate_case(task)
    return load_case_paths(task, case_dir)


def with_sketch_override(task, paths: CasePaths, sketch_override: Path | None) -> CasePaths:
    if not sketch_override:
        return paths
    normalized = normalize_sketch_override(task, paths, sketch_override)
    if normalized is None:
        return paths
    return dataclasses.replace(paths, sketch=normalized)


def resolve_case(
    task,
    *,
    case_dir: Path | None,
    sketch_override: Path | None,
    regenerate: bool,
) -> CasePaths:
    if regenerate:
        paths = generate_case(task)
    else:
        paths = ensure_case(task) if case_dir is None else load_case_paths(task, case_dir)
    return with_sketch_override(task, paths, sketch_override)


def lint_case_platform_file(task, paths: CasePaths) -> None:
    if task.board_profile.backend == "renode":
        from .renode import validate_renode_case

        validate_renode_case(task, paths.diagram, paths.resc)
        return
    validate_diagram_file(paths.diagram, task)


def build_single_task(
    task,
    *,
    case_dir: Path | None,
    sketch_override: Path | None,
    regenerate: bool,
    arduino_cli: str,
    idf_py: str = "idf.py",
    west: str = "west",
) -> dict[str, Any]:
    if not task.is_supported:
        return unsupported_task_result(task)
    try:
        paths = resolve_case(
            task,
            case_dir=case_dir,
            sketch_override=sketch_override,
            regenerate=regenerate,
        )
        build_case(task, paths, arduino_cli=arduino_cli, idf_py=idf_py, west=west)
        firmware_hex, firmware_elf = expected_firmware_paths(paths)
        return result_payload(
            PASS,
            "build completed and firmware artifacts exist",
            {
                "task_id": task.task_id,
                "case_path": str(paths.case_dir),
                "sketch_path": str(paths.sketch),
                "firmware_image": str(paths.firmware_image),
                "firmware_hex": str(firmware_hex),
                "firmware_elf": str(firmware_elf),
            },
        )
    except BuildSimulationError as exc:
        return result_payload(
            exc.classification,
            str(exc),
            failure_stage=exc.failure_stage,
            failure_source=exc.failure_source,
        )
    except (ConfigError, CaseConfigError, DiagramError, ScenarioError, RenodeConfigError) as exc:
        return result_payload(SIM_INFRA_FAIL, str(exc), failure_source=SOURCE_HARNESS)


def run_single_task(
    task,
    *,
    case_dir: Path | None,
    sketch_override: Path | None,
    use_existing_artifacts: bool,
    regenerate: bool,
    simulation_time_ms: int | None,
    arduino_cli: str,
    wokwi_cli: str,
    idf_py: str = "idf.py",
    west: str = "west",
    renode_cli: str = "renode",
    archived_vcd: str | None,
    require_provenance: bool = True,
    allow_tool_version_mismatch: bool = False,
) -> dict[str, Any]:
    if not task.is_supported:
        return unsupported_task_result(task)
    try:
        paths = resolve_case(
            task,
            case_dir=case_dir,
            sketch_override=sketch_override,
            regenerate=regenerate,
        )
        paths = with_archived_vcd(paths, archived_vcd)
        if not use_existing_artifacts and not allow_tool_version_mismatch:
            ensure_tool_versions_compatible(
                arduino_cli=arduino_cli,
                idf_py=idf_py,
                wokwi_cli=wokwi_cli,
                west=west,
                renode_cli=renode_cli,
                build_kind=task.board_profile.build_kind,
            )
        lint_case_platform_file(task, paths)
        if use_existing_artifacts:
            prepare_artifacts(
                task,
                paths,
                use_existing_artifacts=True,
                simulation_time_ms=simulation_time_ms,
                arduino_cli=arduino_cli,
                idf_py=idf_py,
                wokwi_cli=wokwi_cli,
                west=west,
                renode_cli=renode_cli,
                require_provenance=require_provenance,
                ignore_vcd_provenance=archived_vcd is not None,
                enforce_tool_versions=not allow_tool_version_mismatch,
            )
            return validate_case(task, paths)
        return run_case(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            arduino_cli=arduino_cli,
            idf_py=idf_py,
            wokwi_cli=wokwi_cli,
            west=west,
            renode_cli=renode_cli,
            command="run",
        )
    except BuildSimulationError as exc:
        return result_payload(
            exc.classification,
            str(exc),
            failure_stage=exc.failure_stage,
            failure_source=exc.failure_source,
        )
    except (ConfigError, CaseConfigError, DiagramError, ScenarioError, RenodeConfigError) as exc:
        return result_payload(SIM_INFRA_FAIL, str(exc), failure_source=SOURCE_HARNESS)
    except (VcdParseError, SerialLogError, OSError, ValueError, json.JSONDecodeError) as exc:
        return result_payload(SIM_OUTPUT_FAIL, str(exc), failure_source=SOURCE_ARTIFACT)
    except StaticCheckError as exc:
        return result_payload(FAIL, str(exc), failure_source=SOURCE_USER_CODE)


def summarize(results: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        benchmark_result = result["result"]
        summary[benchmark_result] = summary.get(benchmark_result, 0) + 1
    return summary


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluate_submissions(args: argparse.Namespace) -> dict[str, Any]:
    if args.if_retries < 0:
        raise ConfigError("--if-retries must be non-negative")
    rows = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        for task in selected_tasks(args):
            row = evaluate_one_submission(task, args)
            rows.append(row)
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return {
        "output": str(args.output),
        "tasks": len(rows),
        "summary": summarize([row["final_result"] for row in rows]),
    }


def evaluate_one_submission(task, args: argparse.Namespace) -> dict[str, Any]:
    sketch_path = submission_path_for_task(task, args.sketch_dir)
    attempts = []
    max_attempts = args.if_retries + 1
    for attempt_index in range(1, max_attempts + 1):
        attempt = timed_run_single_task(
            task,
            case_dir=None,
            sketch_override=sketch_path,
            use_existing_artifacts=False,
            regenerate=args.regenerate,
            simulation_time_ms=args.simulation_time_ms,
            arduino_cli=args.arduino_cli,
            idf_py=args.idf_py,
            wokwi_cli=args.wokwi_cli,
            west=args.west,
            renode_cli=args.renode,
            archived_vcd=None,
            require_provenance=True,
            allow_tool_version_mismatch=args.allow_tool_version_mismatch,
            attempt_index=attempt_index,
        )
        attempts.append(attempt)
        if attempt["result"]["result"] != "IF":
            break
    return benchmark_row(task, sketch_path, attempts, args)


def measure_repeatability(args: argparse.Namespace) -> dict[str, Any]:
    if args.runs <= 0:
        raise ConfigError("--runs must be positive")
    rows = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        for task in selected_tasks(args):
            attempts = []
            for attempt_index in range(1, args.runs + 1):
                attempts.append(
                    timed_run_single_task(
                        task,
                        case_dir=None,
                        sketch_override=None,
                        use_existing_artifacts=False,
                        regenerate=args.regenerate,
                        simulation_time_ms=args.simulation_time_ms,
                        arduino_cli=args.arduino_cli,
                        idf_py=args.idf_py,
                        wokwi_cli=args.wokwi_cli,
                        west=args.west,
                        renode_cli=args.renode,
                        archived_vcd=None,
                        require_provenance=True,
                        allow_tool_version_mismatch=args.allow_tool_version_mismatch,
                        attempt_index=attempt_index,
                    )
                )
            row = repeatability_row(task, attempts, args)
            rows.append(row)
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return {
        "output": str(args.output),
        "tasks": len(rows),
        "flakes": sum(1 for row in rows if row["flaky"]),
    }


def timed_run_single_task(task, *, attempt_index: int, **kwargs) -> dict[str, Any]:
    started_at = utc_now()
    start = time.perf_counter()
    result = run_single_task(task, **kwargs)
    duration_s = time.perf_counter() - start
    return {
        "attempt": attempt_index,
        "started_at": started_at,
        "ended_at": utc_now(),
        "duration_s": round(duration_s, 6),
        "result": result,
    }


def benchmark_row(task, sketch_path: Path, attempts: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    final_result = attempts[-1]["result"]
    return {
        "task_id": task.task_id,
        "platform": task.platform,
        "level": task.level,
        "prompt_path": str(task.prompt_path),
        "prompt_hash": hash_file(task.prompt_path),
        "sketch_path": str(sketch_path),
        "sketch_hash": hash_file(sketch_path),
        "final_result": final_result,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "tool_versions": tool_version_report(
            arduino_cli=args.arduino_cli,
            idf_py=args.idf_py,
            wokwi_cli=args.wokwi_cli,
            west=args.west,
            renode_cli=args.renode,
            build_kind=task.board_profile.build_kind,
        ),
    }


def repeatability_row(task, attempts: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    signatures = {
        json.dumps(attempt["result"], sort_keys=True)
        for attempt in attempts
    }
    non_bc = [attempt for attempt in attempts if attempt["result"]["result"] != "BC"]
    return {
        "task_id": task.task_id,
        "platform": task.platform,
        "level": task.level,
        "prompt_path": str(task.prompt_path),
        "prompt_hash": hash_file(task.prompt_path),
        "reference_sketch_path": str(case_dir_for_task(task) / "sketch" / task.sketch_name),
        "reference_sketch_hash": hash_path(case_dir_for_task(task) / "sketch" / task.sketch_name),
        "runs": len(attempts),
        "flaky": bool(non_bc or len(signatures) > 1),
        "attempts": attempts,
        "tool_versions": tool_version_report(
            arduino_cli=args.arduino_cli,
            idf_py=args.idf_py,
            wokwi_cli=args.wokwi_cli,
            west=args.west,
            renode_cli=args.renode,
            build_kind=task.board_profile.build_kind,
        ),
    }


def submission_path_for_task(task, sketch_dir: Path) -> Path:
    if task.board_profile.build_kind in {"espidf", "zephyr"}:
        project = sketch_dir / task.task_id
        if project.exists():
            return project
        return sketch_dir / f"{task.task_id}.c"
    return sketch_dir / f"{task.task_id}.ino"


def unsupported_task_payload(task) -> dict[str, str]:
    return {
        "task_id": task.task_id,
        "status": str(task.support.get("status", "unsupported")),
        "reason": task.support_reason,
    }


def unsupported_task_result(task) -> dict[str, Any]:
    return result_payload(
        SIM_INFRA_FAIL,
        f"{task.task_id} is {task.support.get('status', 'unsupported')}: {task.support_reason}",
        unsupported_task_payload(task),
        failure_source=SOURCE_HARNESS,
    )


def print_many_or_one(results: list[dict[str, Any]]) -> None:
    if len(results) == 1:
        print(json.dumps(results[0], indent=2))
    else:
        print(json.dumps({"results": results, "summary": summarize(results)}, indent=2))


def run_doctor(*, platform: str = "arduino_mega") -> dict[str, Any]:
    profile = board_profile_for_platform(platform)
    version_report = tool_version_report(build_kind=profile.build_kind)
    version_check = {
        "name": "pinned tool versions",
        "ok": version_report["ok"],
        "expected": version_report["expected"],
        "actual": version_report["actual"],
        "mismatches": version_report["mismatches"],
    }
    if profile.build_kind == "zephyr":
        checks = [
            check_python_package("yaml", "PyYAML"),
            check_command(renode_module.renode_executable(), "--version"),
            check_command(renode_module.west_executable(), "--version"),
            check_zephyr_workspace(),
            check_zephyr_build_tools(),
            version_check,
            check_writable_artifacts(),
        ]
        return {"ok": all(check["ok"] for check in checks), "checks": checks}
    build_tool_check = (
        check_command("idf.py", "--version")
        if profile.build_kind == "espidf"
        else check_command("arduino-cli", "version")
    )
    checks = [
        check_python_package("yaml", "PyYAML"),
        build_tool_check,
        check_command("wokwi-cli", "--version"),
        version_check,
        check_env("WOKWI_CLI_TOKEN"),
        check_wokwi_help(),
        check_writable_artifacts(),
    ]
    if profile.build_kind == "arduino":
        checks.insert(-2, check_arduino_core(profile))
    return {
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
    }


def check_zephyr_workspace() -> dict[str, Any]:
    workspace = renode_module.zephyr_workspace()
    zephyr_dir = workspace / "zephyr"
    revision = renode_module.zephyr_revision(workspace)
    ok = zephyr_dir.exists() and revision is not None
    return {
        "name": "Zephyr workspace",
        "ok": ok,
        "path": str(workspace),
        "zephyr_revision": revision,
        "reason": None if ok else f"no west workspace with a zephyr checkout at {workspace} (set ZEPHYR_WORKSPACE)",
    }


def check_zephyr_build_tools() -> dict[str, Any]:
    env = renode_module.zephyr_build_env()
    missing = []
    for tool in ("cmake", "ninja"):
        if not shutil.which(tool, path=env.get("PATH")):
            missing.append(tool)
    stage_root = renode_module.zephyr_build_root()
    reason = None
    ok = not missing
    if missing:
        reason = f"not found on PATH or known install locations: {', '.join(missing)}"
    elif " " in str(stage_root):
        ok = False
        reason = f"Zephyr staging dir contains spaces: {stage_root} (set IOTBENCH_ZEPHYR_BUILD_ROOT)"
    return {
        "name": "Zephyr build tools (cmake, ninja)",
        "ok": ok,
        "staging_dir": str(stage_root),
        "reason": reason,
    }


def check_python_package(module: str, label: str) -> dict[str, Any]:
    try:
        __import__(module)
    except ImportError as exc:
        return {"name": label, "ok": False, "reason": str(exc)}
    return {"name": label, "ok": True}


def check_command(command: str, *args: str) -> dict[str, Any]:
    path = shutil.which(command)
    if not path:
        return {"name": command, "ok": False, "reason": "not found on PATH"}
    try:
        completed = subprocess.run(
            command_with_windows_batch_wrapper(path, list(args)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": command, "ok": False, "path": path, "reason": str(exc)}
    output = (completed.stdout or completed.stderr).strip()
    return {
        "name": command,
        "ok": completed.returncode == 0,
        "path": path,
        "version": parse_tool_version(command, output),
        "reason": None if completed.returncode == 0 else output,
    }


def check_env(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(os.environ.get(name)),
        "reason": None if os.environ.get(name) else f"{name} is not set",
    }


def check_arduino_avr() -> dict[str, Any]:
    return check_arduino_core(board_profile_for_platform("arduino_mega"))


def check_arduino_core(profile) -> dict[str, Any]:
    core = ":".join(profile.fqbn.split(":")[:2])
    try:
        completed = subprocess.run(
            ["arduino-cli", "core", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": f"Arduino core {core}", "ok": False, "reason": str(exc)}
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return {
        "name": f"Arduino core {core}",
        "ok": completed.returncode == 0 and core in output,
        "reason": None if completed.returncode == 0 and core in output else output.strip(),
    }


def check_wokwi_help() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["wokwi-cli", "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": "Wokwi CLI flags", "ok": False, "reason": str(exc)}
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    required = ["--vcd-file", "--serial-log-file", "--scenario"]
    missing = [flag for flag in required if flag not in output]
    return {
        "name": "Wokwi CLI flags",
        "ok": completed.returncode == 0 and not missing,
        "missing": missing,
        "reason": None if completed.returncode == 0 and not missing else output.strip(),
    }


def check_writable_artifacts() -> dict[str, Any]:
    path = Path.cwd() / "cases"
    probe = path / ".doctor-write-test"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return {"name": "case artifact directories", "ok": False, "path": str(path), "reason": str(exc)}
    return {"name": "case artifact directories", "ok": True, "path": str(path)}


if __name__ == "__main__":
    raise SystemExit(main())

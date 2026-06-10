"""Unified CLI for generating, running, and validating benchmark tasks."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import ConfigError, iter_tasks, load_task
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
    case_dir_for_task,
    expected_firmware_paths,
    generate_case,
    load_case_paths,
    normalize_sketch_override,
    prepare_artifacts,
    run_case,
    with_archived_vcd,
)
from .scenarios import ScenarioError
from .serial import SerialLogError
from .validators import StaticCheckError, VcdParseError, validate_task


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="IoT-Bench Arduino task harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_task_selection(subparsers.add_parser("generate", help="generate case artifacts"))
    build = subparsers.add_parser("build", help="compile sketches and verify firmware artifacts")
    add_task_selection(build)
    build.add_argument("--case", type=Path, help="case directory to build")
    build.add_argument("--sketch", type=Path, help="submitted sketch directory or .ino file")
    build.add_argument("--regenerate", action="store_true")
    build.add_argument("--arduino-cli", default="arduino-cli")

    add_task_selection(subparsers.add_parser("lint", help="locally lint generated diagrams"))
    subparsers.add_parser("doctor", help="check local benchmark tooling")

    run = subparsers.add_parser("run", help="run simulation and validate task artifacts")
    add_task_selection(run)
    add_run_options(run)

    validate = subparsers.add_parser(
        "validate-artifacts", help="validate existing artifacts without running Wokwi"
    )
    add_task_selection(validate, require_task=True)
    validate.add_argument("--case", type=Path, help="case directory to validate")
    validate.add_argument("--sketch", type=Path, help="submitted sketch directory or .ino file")
    validate.add_argument("--archived-vcd", help="validate archived VCD by filename or 'latest'")

    return parser.parse_args(argv)


def add_task_selection(parser: argparse.ArgumentParser, *, require_task: bool = False) -> None:
    parser.add_argument("--task", required=require_task, help="task id, e.g. blink_led_1hz")
    parser.add_argument("--platform", default="arduino_mega")
    parser.add_argument("--level", default="level1")


def add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--case", type=Path, help="case directory to run")
    parser.add_argument("--sketch", type=Path, help="submitted sketch directory or .ino file")
    parser.add_argument("--use-existing-artifacts", action="store_true")
    parser.add_argument("--regenerate", action="store_true")
    parser.add_argument("--simulation-time-ms", type=int)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    parser.add_argument("--wokwi-cli", default="wokwi-cli")


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
        if args.command == "build":
            tasks = selected_tasks(args)
            results = [
                build_single_task(
                    task,
                    case_dir=args.case,
                    sketch_override=args.sketch,
                    regenerate=args.regenerate,
                    arduino_cli=args.arduino_cli,
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
                validate_diagram_file(paths.diagram, task)
                linted.append(str(paths.diagram))
            print(json.dumps({"linted": linted, "unsupported": unsupported}, indent=2))
            return 0
        if args.command == "doctor":
            print(json.dumps(run_doctor(), indent=2))
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
                wokwi_cli="wokwi-cli",
                archived_vcd=args.archived_vcd,
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
                    wokwi_cli=args.wokwi_cli,
                    archived_vcd=None,
                )
                for task in tasks
            ]
            print_many_or_one(results)
            return 0
    except (ConfigError, CaseConfigError, DiagramError, ScenarioError) as exc:
        return emit_result(SIM_INFRA_FAIL, str(exc), failure_source=SOURCE_HARNESS)

    return emit_result(FAIL, f"unsupported command: {args.command}", failure_source=SOURCE_HARNESS)


def selected_tasks(args: argparse.Namespace):
    if args.task:
        return [load_task(args.task, platform=args.platform, level=args.level)]
    return list(iter_tasks(platform=args.platform, level=args.level))


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
    return CasePaths(
        task_id=paths.task_id,
        case_id=paths.case_id,
        case_dir=paths.case_dir,
        sketch=normalized,
        diagram=paths.diagram,
        wokwi_toml=paths.wokwi_toml,
        build_dir=paths.build_dir,
        fqbn=paths.fqbn,
        vcd=paths.vcd,
        scenario=paths.scenario,
        serial_log=paths.serial_log,
    )


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


def build_single_task(
    task,
    *,
    case_dir: Path | None,
    sketch_override: Path | None,
    regenerate: bool,
    arduino_cli: str,
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
        build_case(task, paths, arduino_cli=arduino_cli)
        firmware_hex, firmware_elf = expected_firmware_paths(paths)
        return result_payload(
            PASS,
            "build completed and firmware artifacts exist",
            {
                "task_id": task.task_id,
                "case_path": str(paths.case_dir),
                "sketch_path": str(paths.sketch),
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
    except (ConfigError, CaseConfigError, DiagramError, ScenarioError) as exc:
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
    archived_vcd: str | None,
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
        validate_diagram_file(paths.diagram, task)
        if use_existing_artifacts:
            prepare_artifacts(
                task,
                paths,
                use_existing_artifacts=True,
                simulation_time_ms=simulation_time_ms,
                arduino_cli=arduino_cli,
                wokwi_cli=wokwi_cli,
            )
            return validate_task(task, paths).payload()
        return run_case(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            arduino_cli=arduino_cli,
            wokwi_cli=wokwi_cli,
            command="run",
        )
    except BuildSimulationError as exc:
        return result_payload(
            exc.classification,
            str(exc),
            failure_stage=exc.failure_stage,
            failure_source=exc.failure_source,
        )
    except (ConfigError, CaseConfigError, DiagramError, ScenarioError) as exc:
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


def run_doctor() -> dict[str, Any]:
    checks = [
        check_python_package("yaml", "PyYAML"),
        check_command("arduino-cli", "version"),
        check_command("wokwi-cli", "--version"),
        check_env("WOKWI_CLI_TOKEN"),
        check_arduino_avr(),
        check_wokwi_help(),
        check_writable_artifacts(),
    ]
    return {
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
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
            [command, *args],
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
        "version": output.splitlines()[0] if output else None,
        "reason": None if completed.returncode == 0 else output,
    }


def check_env(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(os.environ.get(name)),
        "reason": None if os.environ.get(name) else f"{name} is not set",
    }


def check_arduino_avr() -> dict[str, Any]:
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
        return {"name": "Arduino AVR platform", "ok": False, "reason": str(exc)}
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return {
        "name": "Arduino AVR platform",
        "ok": completed.returncode == 0 and "arduino:avr" in output,
        "reason": None if completed.returncode == 0 and "arduino:avr" in output else output.strip(),
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

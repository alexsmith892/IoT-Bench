#!/usr/bin/env python3
"""Shared Wokwi compile/simulation runner for case validators."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from validator_result import (
    COMPILE_FAIL,
    SIM_INFRA_FAIL,
    SIM_OUTPUT_FAIL,
    STAGE_COMPILE,
    STAGE_SIM_INFRA,
    STAGE_SIM_OUTPUT,
)


DEFAULT_FQBN = "arduino:avr:mega"


class RunnerError(Exception):
    """Base class for expected runner errors."""


class CaseConfigError(RunnerError):
    """Raised when a case manifest or explicit path set is invalid."""


class BuildSimulationError(RunnerError):
    """Raised when compile/simulation fails or no generated VCD is produced."""

    def __init__(
        self,
        message: str,
        *,
        classification: str,
        failure_stage: str,
    ) -> None:
        super().__init__(message)
        self.classification = classification
        self.failure_stage = failure_stage


@dataclass(frozen=True)
class WokwiCaseConfig:
    sketch: Path
    diagram: Path
    vcd: Path
    case_dir: Path
    build_dir: Path
    wokwi_toml: Path
    fqbn: str
    signal_name: str
    expected_pin: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_case_dir(case_id: str) -> Path:
    return repo_root() / "cases" / case_id


def resolve_runner_config(args, default_case: Path) -> WokwiCaseConfig:
    """Resolve CLI inputs into a self-contained case configuration.

    With no positional paths or --case, validators run their own default case.
    Explicit positional paths are still supported for ad-hoc debugging.
    """

    if getattr(args, "case", None):
        config = load_case_config(args.case)
        return with_archived_vcd(config, getattr(args, "archived_vcd", None))

    sketch = getattr(args, "sketch", None)
    diagram = getattr(args, "diagram", None)
    vcd = getattr(args, "vcd", None)
    if sketch or diagram or vcd:
        if not sketch or not diagram:
            raise CaseConfigError(
                "explicit path mode requires at least sketch and diagram paths"
            )
        config = config_from_explicit_paths(sketch, diagram, vcd)
        return with_archived_vcd(config, getattr(args, "archived_vcd", None))

    config = load_case_config(default_case)
    return with_archived_vcd(config, getattr(args, "archived_vcd", None))


def load_case_config(case_dir: Path) -> WokwiCaseConfig:
    case_dir = case_dir.resolve()
    manifest_path = case_dir / "case.json"
    if not manifest_path.exists():
        raise CaseConfigError(f"case manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    paths = manifest.get("paths", {})
    signal = manifest.get("observed_signal", {})
    board = manifest.get("board", {})

    return WokwiCaseConfig(
        sketch=required_case_path(case_dir, paths, "sketch"),
        diagram=required_case_path(case_dir, paths, "diagram"),
        vcd=required_case_path(case_dir, paths, "vcd"),
        case_dir=case_dir,
        build_dir=case_dir / paths.get("build", "artifacts/build"),
        wokwi_toml=case_dir / paths.get("wokwi", "wokwi.toml"),
        fqbn=board.get("fqbn", DEFAULT_FQBN),
        signal_name=signal.get("vcd_name", "D0"),
        expected_pin=str(signal.get("expected_connection", "GPIO 3")).split()[-1],
    )


def required_case_path(case_dir: Path, paths: dict, key: str) -> Path:
    raw_path = paths.get(key)
    if not raw_path:
        raise CaseConfigError(f"case manifest is missing paths.{key}")
    return case_dir / raw_path


def config_from_explicit_paths(
    sketch: Path, diagram: Path, vcd: Path | None
) -> WokwiCaseConfig:
    sketch = sketch.resolve()
    diagram = diagram.resolve()
    case_dir = diagram.parent
    return WokwiCaseConfig(
        sketch=sketch,
        diagram=diagram,
        vcd=(vcd.resolve() if vcd else case_dir / "artifacts" / "logic" / "wokwi.vcd"),
        case_dir=case_dir,
        build_dir=case_dir / "artifacts" / "build",
        wokwi_toml=case_dir / "wokwi.toml",
        fqbn=DEFAULT_FQBN,
        signal_name="D0",
        expected_pin="3",
    )


def with_archived_vcd(
    config: WokwiCaseConfig, archived_vcd: Path | str | None
) -> WokwiCaseConfig:
    if not archived_vcd:
        return config
    return replace(config, vcd=resolve_archived_vcd(config, archived_vcd))


def resolve_archived_vcd(config: WokwiCaseConfig, archived_vcd: Path | str) -> Path:
    requested = Path(archived_vcd)
    archive_dir = vcd_archive_dir(config)

    if str(archived_vcd).lower() == "latest":
        archived = sorted(archive_dir.glob("*.vcd"), key=lambda path: path.name)
        if not archived:
            raise CaseConfigError(f"no archived VCDs found in {archive_dir}")
        return archived[-1]

    if requested.is_absolute():
        return requested

    candidates = [
        archive_dir / requested,
        config.case_dir / requested,
        requested.resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]


def prepare_vcd(
    config: WokwiCaseConfig,
    *,
    use_existing_vcd: bool,
    simulation_time_ms: int,
    arduino_cli: str,
    wokwi_cli: str,
) -> None:
    """Ensure config.vcd exists, generating it through Wokwi by default."""

    if use_existing_vcd:
        if not config.vcd.exists():
            raise BuildSimulationError(
                f"VCD not found: {config.vcd}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
            )
        return

    if not config.sketch.exists():
        raise BuildSimulationError(
            f"sketch path not found: {config.sketch}",
            classification=COMPILE_FAIL,
            failure_stage=STAGE_COMPILE,
        )
    if not config.diagram.exists():
        raise BuildSimulationError(
            f"diagram.json not found: {config.diagram}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
        )
    if not config.wokwi_toml.exists():
        raise BuildSimulationError(
            f"wokwi.toml not found: {config.wokwi_toml}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
        )

    config.build_dir.mkdir(parents=True, exist_ok=True)
    config.vcd.parent.mkdir(parents=True, exist_ok=True)
    archive_existing_vcd(config)

    compile_cmd = [
        arduino_cli,
        "compile",
        "-e",
        "-b",
        config.fqbn,
        "--build-path",
        str(config.build_dir),
        str(config.sketch),
    ]
    run_checked(
        compile_cmd,
        cwd=config.case_dir,
        stage="compile",
        command_failure_classification=COMPILE_FAIL,
        command_failure_stage=STAGE_COMPILE,
        infra_failure_classification=SIM_INFRA_FAIL,
        infra_failure_stage=STAGE_SIM_INFRA,
    )

    wokwi_cmd = [
        wokwi_cli,
        str(config.case_dir),
        "--diagram-file",
        relative_to_project(config.diagram, config.case_dir),
        "--timeout",
        str(simulation_time_ms),
        "--timeout-exit-code",
        "0",
        "--vcd-file",
        relative_to_project(config.vcd, config.case_dir),
    ]
    run_checked(
        wokwi_cmd,
        cwd=config.case_dir,
        stage="wokwi simulation",
        timeout_s=max(30.0, simulation_time_ms / 1000.0 + 20.0),
        command_failure_classification=SIM_INFRA_FAIL,
        command_failure_stage=STAGE_SIM_INFRA,
        infra_failure_classification=SIM_INFRA_FAIL,
        infra_failure_stage=STAGE_SIM_INFRA,
    )

    if not config.vcd.exists():
        raise BuildSimulationError(
            f"Wokwi did not produce VCD at {config.vcd}",
            classification=SIM_OUTPUT_FAIL,
            failure_stage=STAGE_SIM_OUTPUT,
        )
    if config.vcd.stat().st_size == 0:
        raise BuildSimulationError(
            f"Wokwi produced an empty VCD at {config.vcd}",
            classification=SIM_OUTPUT_FAIL,
            failure_stage=STAGE_SIM_OUTPUT,
        )


def archive_existing_vcd(config: WokwiCaseConfig) -> Path | None:
    vcd_path = config.vcd
    if not vcd_path.exists():
        return None

    archive_path = next_archive_vcd_path(config, vcd_path)
    try:
        vcd_path.replace(archive_path)
    except OSError as exc:
        raise BuildSimulationError(
            f"could not archive stale VCD {vcd_path} to {archive_path}: {exc}",
            classification=SIM_OUTPUT_FAIL,
            failure_stage=STAGE_SIM_OUTPUT,
        ) from exc
    return archive_path


def next_archive_vcd_path(config: WokwiCaseConfig, vcd_path: Path) -> Path:
    archive_dir = vcd_archive_dir(config)
    archive_dir.mkdir(parents=True, exist_ok=True)

    case_id = safe_filename_part(config.case_dir.name)
    original_stem = safe_filename_part(vcd_path.stem) or "wokwi"
    suffix = vcd_path.suffix or ".vcd"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base_name = f"{case_id}__{timestamp}__{original_stem}"

    candidate = archive_dir / f"{base_name}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = archive_dir / f"{base_name}__{counter}{suffix}"
        counter += 1
    return candidate


def vcd_archive_dir(config: WokwiCaseConfig) -> Path:
    return config.case_dir / "artifacts" / "archive" / "vcd"


def safe_filename_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def run_checked(
    command: list[str],
    *,
    cwd: Path,
    stage: str,
    timeout_s: float | None = None,
    command_failure_classification: str,
    command_failure_stage: str,
    infra_failure_classification: str,
    infra_failure_stage: str,
) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise BuildSimulationError(
            f"{stage} failed: {command[0]} was not found on PATH",
            classification=infra_failure_classification,
            failure_stage=infra_failure_stage,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildSimulationError(
            f"{stage} timed out after {timeout_s:.1f}s",
            classification=command_failure_classification,
            failure_stage=command_failure_stage,
        ) from exc
    except OSError as exc:
        raise BuildSimulationError(
            f"{stage} failed: {exc}",
            classification=infra_failure_classification,
            failure_stage=infra_failure_stage,
        ) from exc

    if completed.returncode != 0:
        raise BuildSimulationError(
            f"{stage} failed with exit code {completed.returncode}: "
            f"{short_process_output(completed)}",
            classification=command_failure_classification,
            failure_stage=command_failure_stage,
        )


def short_process_output(completed: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(
        part.strip()
        for part in (completed.stderr, completed.stdout)
        if part and part.strip()
    )
    if not output:
        return "no command output"
    return output[:497] + "..." if len(output) > 500 else output


def relative_to_project(path: Path, project_dir: Path) -> str:
    try:
        return path.resolve().relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())

"""Case generation, artifact path resolution, and Wokwi runner helpers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import DEFAULT_FQBN, TaskConfig, load_task, repo_root, to_yaml_text
from .diagrams import generate_diagram, validate_diagram_file, write_diagram
from .results import (
    COMPILE_FAIL,
    PASS,
    SIM_INFRA_FAIL,
    SIM_OUTPUT_FAIL,
    STAGE_COMPILE,
    STAGE_SIM_INFRA,
    STAGE_SIM_OUTPUT,
    result_payload,
)
from .scenarios import generate_scenario, write_scenario


class RunnerError(Exception):
    """Base class for expected runner errors."""


class CaseConfigError(RunnerError):
    """Raised when a case manifest or explicit path set is invalid."""


class BuildSimulationError(RunnerError):
    """Raised when compile/simulation fails or expected artifacts are absent."""

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
class CasePaths:
    task_id: str
    case_id: str
    case_dir: Path
    sketch: Path
    diagram: Path
    wokwi_toml: Path
    build_dir: Path
    fqbn: str
    vcd: Path | None = None
    scenario: Path | None = None
    serial_log: Path | None = None

    @property
    def firmware_hex(self) -> Path:
        return expected_firmware_paths(self)[0]

    @property
    def firmware_elf(self) -> Path:
        return expected_firmware_paths(self)[1]

    @property
    def sketch_name(self) -> str:
        return self.sketch.name if self.sketch.is_dir() else self.sketch.stem


def case_dir_for_task(task: TaskConfig, root: Path | None = None) -> Path:
    return (root or repo_root()) / "cases" / task.case_id


def generate_case(task: TaskConfig, *, root: Path | None = None) -> CasePaths:
    root = root or repo_root()
    case_dir = case_dir_for_task(task, root)
    sketch_dir = case_dir / "sketch" / task.sketch_name
    paths = case_paths_from_task(task, case_dir)

    write_diagram(paths.diagram, generate_diagram(task))
    scenario_data = generate_scenario(task)
    if paths.scenario:
        write_scenario(paths.scenario, scenario_data)

    write_case_yaml(task, paths)
    write_case_json(task, paths)
    write_wokwi_toml(task, paths)
    ensure_sketch_files(task, sketch_dir)
    ensure_artifact_dirs(paths)
    validate_diagram_file(paths.diagram, task)
    return paths


def ensure_artifact_dirs(paths: CasePaths) -> None:
    for path in (
        paths.case_dir / "artifacts" / "build",
        paths.case_dir / "artifacts" / "logic",
        paths.case_dir / "artifacts" / "serial",
        paths.case_dir / "artifacts" / "archive" / "vcd",
        paths.case_dir / "artifacts" / "archive" / "serial",
    ):
        path.mkdir(parents=True, exist_ok=True)


def case_paths_from_task(task: TaskConfig, case_dir: Path) -> CasePaths:
    sketch = case_dir / "sketch" / task.sketch_name
    scenario = case_dir / "scenario.yaml" if task.scenario else None
    return CasePaths(
        task_id=task.task_id,
        case_id=task.case_id,
        case_dir=case_dir,
        sketch=sketch,
        diagram=case_dir / "diagram.json",
        wokwi_toml=case_dir / "wokwi.toml",
        build_dir=case_dir / "artifacts" / "build",
        fqbn=task.board.get("fqbn", DEFAULT_FQBN),
        vcd=(case_dir / "artifacts" / "logic" / "wokwi.vcd" if task.requires_vcd else None),
        scenario=scenario,
        serial_log=(
            case_dir / "artifacts" / "serial" / "serial.log"
            if task.requires_serial_log
            else None
        ),
    )


def write_case_yaml(task: TaskConfig, paths: CasePaths) -> None:
    data: dict[str, Any] = {
        "task_id": task.task_id,
        "case_id": task.case_id,
        "board": task.board,
        "paths": {
            "sketch": relative_to(paths.sketch, paths.case_dir),
            "diagram": relative_to(paths.diagram, paths.case_dir),
            "wokwi": relative_to(paths.wokwi_toml, paths.case_dir),
            "build": relative_to(paths.build_dir, paths.case_dir),
        },
    }
    if paths.vcd:
        data["paths"]["vcd"] = relative_to(paths.vcd, paths.case_dir)
    if paths.scenario:
        data["paths"]["scenario"] = relative_to(paths.scenario, paths.case_dir)
    if paths.serial_log:
        data["paths"]["serial_log"] = relative_to(paths.serial_log, paths.case_dir)
    (paths.case_dir / "case.yaml").parent.mkdir(parents=True, exist_ok=True)
    (paths.case_dir / "case.yaml").write_text(to_yaml_text(data), encoding="utf-8")


def write_case_json(task: TaskConfig, paths: CasePaths) -> None:
    channels = task.fixture.get("analyzer", {}).get("channels", [])
    data: dict[str, Any] = {
        "id": task.case_id,
        "task": task.task_id,
        "name": task.name,
        "simulator": "wokwi",
        "board": task.board,
        "paths": {
            "sketch": relative_to(paths.sketch, paths.case_dir),
            "diagram": relative_to(paths.diagram, paths.case_dir),
            "wokwi": relative_to(paths.wokwi_toml, paths.case_dir),
            "build": relative_to(paths.build_dir, paths.case_dir),
        },
    }
    if paths.vcd:
        data["paths"]["vcd"] = relative_to(paths.vcd, paths.case_dir)
    if paths.scenario:
        data["paths"]["scenario"] = relative_to(paths.scenario, paths.case_dir)
    if paths.serial_log:
        data["paths"]["serial_log"] = relative_to(paths.serial_log, paths.case_dir)
    if channels:
        data["observed_signal"] = {
            "vcd_name": channels[0]["signal"],
            "expected_connection": f"GPIO {channels[0]['pin']}",
        }
        data["observed_signals"] = [
            {
                "vcd_name": channel["signal"],
                "expected_connection": f"GPIO {channel['pin']}",
            }
            for channel in channels
        ]
    (paths.case_dir / "case.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def write_wokwi_toml(task: TaskConfig, paths: CasePaths) -> None:
    lines = [
        "[wokwi]",
        "version = 1",
        f"firmware = 'artifacts/build/{task.sketch_name}.ino.hex'",
        f"elf = 'artifacts/build/{task.sketch_name}.ino.elf'",
    ]
    if paths.vcd:
        lines.append(f"vcdFile = '{relative_to(paths.vcd, paths.case_dir)}'")
    paths.wokwi_toml.write_text("\n".join(lines) + "\n", encoding="utf-8")


def expected_firmware_paths(paths: CasePaths) -> tuple[Path, Path]:
    if paths.wokwi_toml.exists():
        configured = read_wokwi_firmware_paths(paths)
        if configured:
            return configured
    return (
        paths.build_dir / f"{paths.sketch_name}.ino.hex",
        paths.build_dir / f"{paths.sketch_name}.ino.elf",
    )


def read_wokwi_firmware_paths(paths: CasePaths) -> tuple[Path, Path] | None:
    text = paths.wokwi_toml.read_text(encoding="utf-8")
    firmware = extract_toml_string(text, "firmware")
    elf = extract_toml_string(text, "elf")
    if not firmware or not elf:
        return None
    return paths.case_dir / firmware, paths.case_dir / elf


def extract_toml_string(text: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    return match.group(1) if match else None


def ensure_sketch_files(task: TaskConfig, sketch_dir: Path) -> None:
    sketch_dir.mkdir(parents=True, exist_ok=True)
    sketch_yaml = sketch_dir / "sketch.yaml"
    if not sketch_yaml.exists():
        sketch_yaml.write_text(
            "default_fqbn: arduino:avr:mega\n", encoding="utf-8"
        )
    ino_path = sketch_dir / f"{task.sketch_name}.ino"
    if not ino_path.exists():
        ino_path.write_text(example_sketch(task), encoding="utf-8")


def load_case_paths(
    task: TaskConfig,
    case_dir: Path | None = None,
    *,
    sketch_override: Path | None = None,
) -> CasePaths:
    case_dir = (case_dir or case_dir_for_task(task)).resolve()
    case_yaml = case_dir / "case.yaml"
    case_json = case_dir / "case.json"
    if case_yaml.exists():
        data = yaml.safe_load(case_yaml.read_text(encoding="utf-8"))
    elif case_json.exists():
        data = json.loads(case_json.read_text(encoding="utf-8"))
    else:
        raise CaseConfigError(f"case manifest not found in {case_dir}")

    paths = data.get("paths", {})
    board = data.get("board", task.board)
    sketch = case_dir / required_path(paths, "sketch")
    if sketch_override:
        sketch = sketch_override.resolve()
    return CasePaths(
        task_id=data.get("task_id") or data.get("task") or task.task_id,
        case_id=data.get("case_id") or data.get("id") or task.case_id,
        case_dir=case_dir,
        sketch=sketch,
        diagram=case_dir / required_path(paths, "diagram"),
        wokwi_toml=case_dir / paths.get("wokwi", "wokwi.toml"),
        build_dir=case_dir / paths.get("build", "artifacts/build"),
        fqbn=board.get("fqbn", DEFAULT_FQBN),
        vcd=(case_dir / paths["vcd"] if paths.get("vcd") else None),
        scenario=(case_dir / paths["scenario"] if paths.get("scenario") else None),
        serial_log=(case_dir / paths["serial_log"] if paths.get("serial_log") else None),
    )


def required_path(paths: dict[str, str], key: str) -> str:
    value = paths.get(key)
    if not value:
        raise CaseConfigError(f"case manifest is missing paths.{key}")
    return value


def with_archived_vcd(paths: CasePaths, archived_vcd: str | Path | None) -> CasePaths:
    if not archived_vcd:
        return paths
    if paths.vcd is None:
        raise CaseConfigError("case does not define a VCD path")
    return replace(paths, vcd=resolve_archived_vcd(paths, archived_vcd))


def resolve_archived_vcd(paths: CasePaths, archived_vcd: str | Path) -> Path:
    archive_dir = paths.case_dir / "artifacts" / "archive" / "vcd"
    if str(archived_vcd).lower() == "latest":
        archived = sorted(archive_dir.glob("*.vcd"), key=lambda path: path.name)
        if not archived:
            raise CaseConfigError(f"no archived VCDs found in {archive_dir}")
        return archived[-1]

    requested = Path(archived_vcd)
    if requested.is_absolute():
        return requested
    for candidate in (archive_dir / requested, paths.case_dir / requested, requested.resolve()):
        if candidate.exists():
            return candidate
    return archive_dir / requested


def prepare_artifacts(
    task: TaskConfig,
    paths: CasePaths,
    *,
    use_existing_artifacts: bool,
    simulation_time_ms: int | None = None,
    arduino_cli: str = "arduino-cli",
    wokwi_cli: str = "wokwi-cli",
) -> None:
    if use_existing_artifacts:
        ensure_existing_outputs(task, paths)
        return

    build_case(task, paths, arduino_cli=arduino_cli)
    simulate_case(
        task,
        paths,
        simulation_time_ms=simulation_time_ms,
        wokwi_cli=wokwi_cli,
    )
    ensure_existing_outputs(task, paths)


def build_case(
    task: TaskConfig,
    paths: CasePaths,
    *,
    arduino_cli: str = "arduino-cli",
) -> None:
    ensure_artifact_dirs(paths)

    if not paths.sketch.exists():
        raise BuildSimulationError(
            f"sketch path not found: {paths.sketch}",
            classification=COMPILE_FAIL,
            failure_stage=STAGE_COMPILE,
        )
    if not paths.diagram.exists():
        raise BuildSimulationError(
            f"diagram.json not found: {paths.diagram}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
        )
    if not paths.wokwi_toml.exists():
        raise BuildSimulationError(
            f"wokwi.toml not found: {paths.wokwi_toml}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
        )

    paths.build_dir.mkdir(parents=True, exist_ok=True)

    run_checked(
        [
            arduino_cli,
            "compile",
            "-e",
            "-b",
            paths.fqbn,
            "--build-path",
            str(paths.build_dir),
            str(paths.sketch),
        ],
        cwd=paths.case_dir,
        stage="compile",
        command_failure_classification=COMPILE_FAIL,
        command_failure_stage=STAGE_COMPILE,
        infra_failure_classification=SIM_INFRA_FAIL,
        infra_failure_stage=STAGE_SIM_INFRA,
    )
    ensure_firmware_outputs(paths)


def simulate_case(
    task: TaskConfig,
    paths: CasePaths,
    *,
    simulation_time_ms: int | None = None,
    wokwi_cli: str = "wokwi-cli",
) -> None:
    ensure_artifact_dirs(paths)
    ensure_firmware_outputs(paths)
    if not paths.diagram.exists():
        raise BuildSimulationError(
            f"diagram.json not found: {paths.diagram}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
        )
    if not paths.wokwi_toml.exists():
        raise BuildSimulationError(
            f"wokwi.toml not found: {paths.wokwi_toml}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
        )
    if paths.scenario and not paths.scenario.exists():
        raise BuildSimulationError(
            f"scenario.yaml not found: {paths.scenario}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
        )

    archive_current_outputs(paths)

    timeout_ms = simulation_time_ms or int(task.simulation.get("timeout_ms", 5000))
    wokwi_cmd = [
        wokwi_cli,
        str(paths.case_dir),
        "--diagram-file",
        relative_to(paths.diagram, paths.case_dir),
        "--timeout",
        str(timeout_ms),
        "--timeout-exit-code",
        "0",
    ]
    if paths.vcd:
        paths.vcd.parent.mkdir(parents=True, exist_ok=True)
        wokwi_cmd.extend(["--vcd-file", relative_to(paths.vcd, paths.case_dir)])
    if paths.scenario:
        wokwi_cmd.extend(["--scenario", relative_to(paths.scenario, paths.case_dir)])
    if paths.serial_log:
        paths.serial_log.parent.mkdir(parents=True, exist_ok=True)
        wokwi_cmd.extend(["--serial-log-file", relative_to(paths.serial_log, paths.case_dir)])

    run_checked(
        wokwi_cmd,
        cwd=paths.case_dir,
        stage="wokwi simulation",
        timeout_s=max(30.0, timeout_ms / 1000.0 + 20.0),
        command_failure_classification=SIM_INFRA_FAIL,
        command_failure_stage=STAGE_SIM_INFRA,
        infra_failure_classification=SIM_INFRA_FAIL,
        infra_failure_stage=STAGE_SIM_INFRA,
    )
    ensure_existing_outputs(task, paths)


def run_case(
    task: TaskConfig,
    paths: CasePaths,
    *,
    simulation_time_ms: int | None = None,
    arduino_cli: str = "arduino-cli",
    wokwi_cli: str = "wokwi-cli",
    command: str = "run",
) -> dict[str, Any]:
    build_case(task, paths, arduino_cli=arduino_cli)
    simulate_case(
        task,
        paths,
        simulation_time_ms=simulation_time_ms,
        wokwi_cli=wokwi_cli,
    )
    result = validate_case(task, paths)
    write_verification(task, paths, result, command=command)
    return result


def validate_case(task: TaskConfig, paths: CasePaths) -> dict[str, Any]:
    from .validators import validate_task

    return validate_task(task, paths).payload()


def ensure_firmware_outputs(paths: CasePaths) -> None:
    firmware_hex, firmware_elf = expected_firmware_paths(paths)
    missing = [path for path in (firmware_hex, firmware_elf) if not path.exists()]
    if missing:
        normalize_firmware_outputs(paths)
        missing = [path for path in (firmware_hex, firmware_elf) if not path.exists()]
    if missing:
        names = ", ".join(str(path) for path in missing)
        raise BuildSimulationError(
            f"firmware binary artifact(s) missing after compile: {names}",
            classification=COMPILE_FAIL,
            failure_stage=STAGE_COMPILE,
        )
    for path in (firmware_hex, firmware_elf):
        if path.stat().st_size == 0:
            raise BuildSimulationError(
                f"firmware binary artifact is empty: {path}",
                classification=COMPILE_FAIL,
                failure_stage=STAGE_COMPILE,
            )


def normalize_firmware_outputs(paths: CasePaths) -> None:
    expected_hex, expected_elf = expected_firmware_paths(paths)
    candidates = [
        paths.build_dir / f"{paths.sketch_name}.ino.hex",
        paths.build_dir / f"{paths.sketch_name}.ino.elf",
        *paths.build_dir.rglob(f"{paths.sketch_name}.ino.hex"),
        *paths.build_dir.rglob(f"{paths.sketch_name}.ino.elf"),
    ]
    if paths.sketch.is_dir():
        candidates.extend(paths.sketch.rglob(f"{paths.sketch_name}.ino.hex"))
        candidates.extend(paths.sketch.rglob(f"{paths.sketch_name}.ino.elf"))
    candidates.extend(paths.build_dir.rglob("*.ino.hex"))
    candidates.extend(paths.build_dir.rglob("*.ino.elf"))
    for expected in (expected_hex, expected_elf):
        if expected.exists():
            continue
        same_name = [
            candidate
            for candidate in candidates
            if candidate.name == expected.name and candidate.exists() and candidate != expected
        ]
        same_suffix = [
            candidate
            for candidate in candidates
            if candidate.suffix == expected.suffix and candidate.exists() and candidate != expected
        ]
        copy_from = same_name[0] if same_name else (same_suffix[0] if len(same_suffix) == 1 else None)
        if copy_from:
            expected.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copy_from, expected)


def ensure_existing_outputs(task: TaskConfig, paths: CasePaths) -> None:
    if task.requires_vcd:
        if paths.vcd is None or not paths.vcd.exists():
            raise BuildSimulationError(
                f"VCD not found: {paths.vcd}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
            )
        if paths.vcd.stat().st_size == 0:
            raise BuildSimulationError(
                f"VCD is empty: {paths.vcd}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
            )
    if task.requires_serial_log:
        if paths.serial_log is None or not paths.serial_log.exists():
            raise BuildSimulationError(
                f"serial log not found: {paths.serial_log}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
            )
        if paths.serial_log.stat().st_size == 0:
            raise BuildSimulationError(
                f"serial log is empty: {paths.serial_log}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
            )


def archive_current_outputs(paths: CasePaths) -> None:
    if paths.vcd and paths.vcd.exists():
        archive_path(paths.vcd, paths.case_dir / "artifacts" / "archive" / "vcd")
    if paths.serial_log and paths.serial_log.exists():
        archive_path(paths.serial_log, paths.case_dir / "artifacts" / "archive" / "serial")


def archive_path(path: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base = f"{safe_filename_part(path.parent.parent.parent.name)}__{timestamp}__{safe_filename_part(path.stem)}"
    candidate = archive_dir / f"{base}{path.suffix}"
    counter = 1
    while candidate.exists():
        candidate = archive_dir / f"{base}__{counter}{path.suffix}"
        counter += 1
    shutil.move(str(path), str(candidate))
    return candidate


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
            f"{stage} failed with exit code {completed.returncode}: {short_process_output(completed)}",
            classification=command_failure_classification,
            failure_stage=command_failure_stage,
        )


def write_verification(
    task: TaskConfig,
    paths: CasePaths,
    result: dict[str, Any],
    *,
    command: str,
) -> Path:
    manifest = {
        "task_id": task.task_id,
        "case_id": paths.case_id,
        "command": command,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "arduino_cli_version": command_version("arduino-cli", "version"),
        "wokwi_cli_version": command_version("wokwi-cli", "--version"),
        "sketch_path": relative_to(paths.sketch, paths.case_dir),
        "sketch_hash": hash_path(paths.sketch),
        "diagram_path": relative_to(paths.diagram, paths.case_dir),
        "diagram_hash": hash_file(paths.diagram),
        "scenario_path": relative_to(paths.scenario, paths.case_dir) if paths.scenario else None,
        "scenario_hash": hash_file(paths.scenario) if paths.scenario else None,
        "firmware_hex": relative_to(paths.firmware_hex, paths.case_dir),
        "firmware_hex_hash": hash_file(paths.firmware_hex),
        "firmware_elf": relative_to(paths.firmware_elf, paths.case_dir),
        "firmware_elf_hash": hash_file(paths.firmware_elf),
        "vcd_path": relative_to(paths.vcd, paths.case_dir) if paths.vcd else None,
        "serial_log_path": relative_to(paths.serial_log, paths.case_dir) if paths.serial_log else None,
        "result": result.get("result"),
        "classification": result.get("classification"),
        "failure_stage": result.get("failure_stage"),
        "reason": result.get("reason"),
        "metrics": result.get("metrics", {}),
    }
    path = paths.case_dir / "artifacts" / "verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def command_version(command: str, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            [command, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (completed.stdout or completed.stderr).strip()
    return output.splitlines()[0] if output else None


def hash_path(path: Path) -> str | None:
    if path.is_file():
        return hash_file(path)
    if not path.is_dir():
        return None
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(relative_to(item, path).encode("utf-8"))
            digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def hash_file(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def short_process_output(completed: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(
        part.strip()
        for part in (completed.stderr, completed.stdout)
        if part and part.strip()
    )
    if not output:
        return "no command output"
    return output[:497] + "..." if len(output) > 500 else output


def relative_to(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def safe_filename_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def example_sketch(task: TaskConfig) -> str:
    examples = {
        "blink_two_leds": BLINK_TWO_LEDS,
        "buzzer_doorbell": BUZZER_DOORBELL,
        "button_status_display": BUTTON_STATUS_DISPLAY,
        "button_status_count": BUTTON_STATUS_COUNT,
        "button_press_debounce": BUTTON_PRESS_DEBOUNCE,
        "sensor_pir_human_motion": SENSOR_PIR_HUMAN_MOTION,
        "tmp36_read": TMP36_READ,
    }
    return examples.get(task.task_id, "void setup() {}\nvoid loop() {}\n")


BLINK_TWO_LEDS = """\
const int LED1_PIN = 2;
const int LED2_PIN = 3;
unsigned long lastLed1Ms = 0;
unsigned long lastLed2Ms = 0;
bool led1State = LOW;
bool led2State = LOW;

void setup() {
  pinMode(LED1_PIN, OUTPUT);
  pinMode(LED2_PIN, OUTPUT);
}

void loop() {
  unsigned long now = millis();
  if (now - lastLed1Ms >= 500) {
    lastLed1Ms += 500;
    led1State = !led1State;
    digitalWrite(LED1_PIN, led1State);
  }
  if (now - lastLed2Ms >= 250) {
    lastLed2Ms += 250;
    led2State = !led2State;
    digitalWrite(LED2_PIN, led2State);
  }
}
"""

BUZZER_DOORBELL = """\
const int BUTTON_PIN = 2;
const int BUZZER_PIN = 13;

void setup() {
  pinMode(BUTTON_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
}

void loop() {
  digitalWrite(BUZZER_PIN, digitalRead(BUTTON_PIN) == HIGH ? HIGH : LOW);
}
"""

BUTTON_STATUS_DISPLAY = """\
const int BUTTON_PIN = 2;
bool wasPressed = false;

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT);
}

void loop() {
  bool pressed = digitalRead(BUTTON_PIN) == HIGH;
  if (pressed && !wasPressed) {
    Serial.println("Button Pressed!");
  }
  wasPressed = pressed;
  delay(5);
}
"""

BUTTON_STATUS_COUNT = """\
const int BUTTON_PIN = 2;
bool wasPressed = false;
int count = 0;

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT);
}

void loop() {
  bool pressed = digitalRead(BUTTON_PIN) == HIGH;
  if (pressed && !wasPressed) {
    count++;
    Serial.println(count);
  }
  wasPressed = pressed;
  delay(5);
}
"""

BUTTON_PRESS_DEBOUNCE = """\
const int BUTTON_PIN = 2;
const unsigned long DEBOUNCE_MS = 30;
bool stableState = LOW;
bool lastReading = LOW;
unsigned long lastChangeMs = 0;

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT);
}

void loop() {
  bool reading = digitalRead(BUTTON_PIN);
  unsigned long now = millis();
  if (reading != lastReading) {
    lastChangeMs = now;
    lastReading = reading;
  }
  if ((now - lastChangeMs) > DEBOUNCE_MS && reading != stableState) {
    stableState = reading;
    if (stableState == HIGH) {
      Serial.println("Button Pressed!");
    }
  }
}
"""

SENSOR_PIR_HUMAN_MOTION = """\
const int PIR_PIN = 4;
int lastState = -1;

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);
}

void loop() {
  int state = digitalRead(PIR_PIN);
  if (state != lastState) {
    if (state == HIGH) {
      Serial.println("Motion Detected!");
    } else {
      Serial.println("No Motion Detected!");
    }
    lastState = state;
  }
  delay(10);
}
"""

TMP36_READ = """\
const int TMP36_PIN = A0;

void setup() {
  Serial.begin(115200);
}

void loop() {
  int raw = analogRead(TMP36_PIN);
  float voltage = raw * (5.0 / 1023.0);
  float celsius = (voltage - 0.5) * 100.0;
  Serial.println(celsius, 1);
  delay(100);
}
"""


def load_task_for_case(task_id: str) -> TaskConfig:
    return load_task(task_id)

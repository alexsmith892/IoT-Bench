"""Case generation, artifact path resolution, and Wokwi runner helpers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import hashlib
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import (
    DEFAULT_FQBN,
    TaskConfig,
    load_task,
    repo_root,
    sanitize_variant_id,
    to_yaml_text,
)
from .diagrams import generate_diagram, validate_diagram_file, write_diagram
from .results import (
    COMPILE_FAIL,
    FAIL,
    PASS,
    SOURCE_ARTIFACT,
    SOURCE_ENVIRONMENT,
    SOURCE_HARNESS,
    SOURCE_SIMULATOR,
    SOURCE_USER_CODE,
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
        failure_source: str,
    ) -> None:
        super().__init__(message)
        self.classification = classification
        self.failure_stage = failure_stage
        self.failure_source = failure_source


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
    firmware_extension: str = ".hex"
    vcd: Path | None = None
    scenario: Path | None = None
    serial_log: Path | None = None

    @property
    def firmware_image(self) -> Path:
        return expected_firmware_paths(self)[0]

    @property
    def firmware_hex(self) -> Path:
        return self.firmware_image

    @property
    def firmware_elf(self) -> Path:
        return expected_firmware_paths(self)[1]

    @property
    def sketch_name(self) -> str:
        return self.sketch.name if self.sketch.is_dir() else self.sketch.stem


def case_dir_for_task(task: TaskConfig, root: Path | None = None) -> Path:
    return (root or repo_root()) / "cases" / task.case_id


def generate_case(task: TaskConfig, *, root: Path | None = None) -> CasePaths:
    if not task.is_supported:
        raise CaseConfigError(f"{task.task_id} is {task.support.get('status', 'unsupported')}: {task.support_reason}")
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
    ensure_custom_chip_artifacts(task, paths, root)
    ensure_sketch_files(task, sketch_dir)
    ensure_artifact_dirs(paths)
    validate_diagram_file(paths.diagram, task)
    return paths


def ensure_custom_chip_artifacts(task: TaskConfig, paths: CasePaths, root: Path) -> None:
    if not task.custom_chips:
        return
    source_case_dir = case_dir_for_task(task, repo_root())
    for chip in task.custom_chips:
        binary = Path(str(chip["binary"]).replace("\\", "/"))
        json_name = binary.with_suffix(".json")
        for relative in (binary, json_name):
            destination = paths.case_dir / relative
            if destination.exists():
                continue
            source = source_case_dir / relative
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)


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
        firmware_extension=task.board_profile.firmware_extension,
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
        f"firmware = 'artifacts/build/{task.sketch_name}.ino{paths.firmware_extension}'",
        f"elf = 'artifacts/build/{task.sketch_name}.ino.elf'",
    ]
    if paths.vcd:
        lines.append(f"vcdFile = '{relative_to(paths.vcd, paths.case_dir)}'")
    for chip in task.custom_chips:
        binary = str(chip["binary"]).replace("\\", "/")
        lines.extend(
            [
                "",
                "[[chip]]",
                f"name = '{chip['name']}'",
                f"binary = '{binary}'",
            ]
        )
    paths.wokwi_toml.write_text("\n".join(lines) + "\n", encoding="utf-8")


def expected_firmware_paths(paths: CasePaths) -> tuple[Path, Path]:
    if paths.wokwi_toml.exists():
        configured = read_wokwi_firmware_paths(paths)
        if configured:
            return configured
    return (
        paths.build_dir / f"{paths.sketch_name}.ino{paths.firmware_extension}",
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
            f"default_fqbn: {task.board_profile.fqbn}\n", encoding="utf-8"
        )
    ino_path = sketch_dir / f"{task.sketch_name}.ino"
    if not ino_path.exists() or task.level in {"level2", "level3"}:
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
        firmware_extension=task.board_profile.firmware_extension,
        vcd=(case_dir / paths["vcd"] if paths.get("vcd") else None),
        scenario=(case_dir / paths["scenario"] if paths.get("scenario") else None),
        serial_log=(case_dir / paths["serial_log"] if paths.get("serial_log") else None),
    )


def normalize_sketch_override(task: TaskConfig, paths: CasePaths, sketch_override: Path | None) -> Path | None:
    if sketch_override is None:
        return None
    source = sketch_override.resolve()
    if not source.exists():
        raise BuildSimulationError(
            f"submitted sketch path not found: {source}",
            classification=COMPILE_FAIL,
            failure_stage=STAGE_COMPILE,
            failure_source=SOURCE_USER_CODE,
        )

    destination = paths.case_dir / "artifacts" / "submissions" / task.sketch_name
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    expected_name = f"{task.sketch_name}.ino"
    if source.is_file():
        if source.suffix.lower() != ".ino":
            raise BuildSimulationError(
                f"submitted sketch file must be an .ino file: {source}",
                classification=COMPILE_FAIL,
                failure_stage=STAGE_COMPILE,
                failure_source=SOURCE_USER_CODE,
            )
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination / expected_name)
        return destination

    ino_files = sorted(source.rglob("*.ino"))
    if not ino_files:
        raise BuildSimulationError(
            f"submitted sketch directory contains no .ino file: {source}",
            classification=COMPILE_FAIL,
            failure_stage=STAGE_COMPILE,
            failure_source=SOURCE_USER_CODE,
        )
    matching = [path for path in ino_files if path.name.lower() == expected_name.lower()]
    if matching:
        primary = matching[0]
    elif len(ino_files) == 1:
        primary = ino_files[0]
    else:
        names = ", ".join(str(path.relative_to(source)) for path in ino_files)
        raise BuildSimulationError(
            f"submitted sketch directory has multiple .ino files and none named {expected_name}: {names}",
            classification=COMPILE_FAIL,
            failure_stage=STAGE_COMPILE,
            failure_source=SOURCE_USER_CODE,
        )

    source_root = primary.parent
    shutil.copytree(source_root, destination)
    copied_primary = destination / primary.name
    expected_primary = destination / expected_name
    if copied_primary != expected_primary:
        if expected_primary.exists():
            expected_primary.unlink()
        copied_primary.rename(expected_primary)
    return destination


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
    require_provenance: bool = True,
    ignore_vcd_provenance: bool = False,
    enforce_tool_versions: bool = True,
) -> None:
    if use_existing_artifacts:
        ensure_existing_variant_outputs(task, paths)
        if require_provenance:
            validate_existing_artifact_manifest(
                task,
                paths,
                ignore_vcd=ignore_vcd_provenance,
                arduino_cli=arduino_cli,
                wokwi_cli=wokwi_cli,
                enforce_tool_versions=enforce_tool_versions,
            )
        return

    build_case(task, paths, arduino_cli=arduino_cli)
    if task.simulation_variants:
        simulate_variants(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
        )
    else:
        simulate_case(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
        )
    ensure_existing_variant_outputs(task, paths)


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
            failure_source=SOURCE_USER_CODE,
        )
    if not paths.diagram.exists():
        raise BuildSimulationError(
            f"diagram.json not found: {paths.diagram}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
        )
    if not paths.wokwi_toml.exists():
        raise BuildSimulationError(
            f"wokwi.toml not found: {paths.wokwi_toml}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
        )

    clean_build_dir(paths)

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
        command_failure_source=SOURCE_USER_CODE,
        infra_failure_source=SOURCE_ENVIRONMENT,
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
            failure_source=SOURCE_HARNESS,
        )
    if not paths.wokwi_toml.exists():
        raise BuildSimulationError(
            f"wokwi.toml not found: {paths.wokwi_toml}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
        )
    if paths.scenario and not paths.scenario.exists():
        raise BuildSimulationError(
            f"scenario.yaml not found: {paths.scenario}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
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
        command_failure_source=SOURCE_SIMULATOR,
        infra_failure_source=SOURCE_ENVIRONMENT,
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
    if task.simulation_variants:
        simulate_variants(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
        )
    else:
        simulate_case(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
        )
    result = validate_case(task, paths)
    write_verification(
        task,
        paths,
        result,
        command=command,
        arduino_cli=arduino_cli,
        wokwi_cli=wokwi_cli,
    )
    return result


def validate_case(task: TaskConfig, paths: CasePaths) -> dict[str, Any]:
    if task.simulation_variants:
        return validate_variants(task, paths)
    from .validators import validate_task

    return validate_task(task, paths).payload()


def simulate_variants(
    task: TaskConfig,
    paths: CasePaths,
    *,
    simulation_time_ms: int | None = None,
    wokwi_cli: str = "wokwi-cli",
) -> list[CasePaths]:
    simulated: list[CasePaths] = []
    for variant in task.simulation_variants:
        variant_paths = paths_for_variant(paths, variant_id(variant), variant)
        write_variant_diagram(paths.diagram, variant_paths.diagram, variant)
        proxy = task_for_variant(task, variant)
        if variant_scenario_override(variant) is not None and variant_paths.scenario:
            write_scenario(variant_paths.scenario, generate_scenario(proxy))
        simulate_case(
            proxy,
            variant_paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
        )
        simulated.append(variant_paths)
    return simulated


def ensure_existing_variant_outputs(task: TaskConfig, paths: CasePaths) -> None:
    if task.simulation_variants:
        for variant in task.simulation_variants:
            ensure_existing_outputs(task, paths_for_variant(paths, variant_id(variant), variant))
        return
    ensure_existing_outputs(task, paths)


def validate_variants(task: TaskConfig, paths: CasePaths) -> dict[str, Any]:
    from .serial import SerialLogError
    from .validators import validate_task
    from .vcd import VcdParseError

    variant_results: list[dict[str, Any]] = []
    serial_outputs: dict[str, str] = {}
    metrics: dict[str, Any] = {"variants": variant_results}
    for variant in task.simulation_variants:
        current_id = variant_id(variant)
        variant_paths = paths_for_variant(paths, current_id, variant)
        proxy = task_for_variant(task, variant)
        try:
            result = validate_task(proxy, variant_paths).payload()
        except (SerialLogError, VcdParseError) as exc:
            return result_payload(
                SIM_OUTPUT_FAIL,
                f"variant {current_id} failed: {exc}",
                metrics,
                failure_stage=STAGE_SIM_OUTPUT,
                failure_source=SOURCE_ARTIFACT,
            )
        variant_results.append(
            {
                "id": current_id,
                "attrs": variant.get("attrs") or {},
                "result": result,
                "diagram_path": str(variant_paths.diagram),
                "serial_log_path": str(variant_paths.serial_log) if variant_paths.serial_log else None,
                "vcd_path": str(variant_paths.vcd) if variant_paths.vcd else None,
            }
        )
        if variant_paths.serial_log and variant_paths.serial_log.exists():
            serial_outputs[current_id] = normalize_serial_text(
                variant_paths.serial_log.read_text(encoding="utf-8", errors="replace")
            )
        if result["classification"] != PASS:
            # Preserve the inner classification so infra/artifact problems in a
            # variant stay IF (and compile problems stay CF) instead of being
            # recorded as a behavior failure of the submission.
            return result_payload(
                result["classification"],
                f"variant {current_id} failed: {result['reason']}",
                metrics,
                failure_stage=result.get("failure_stage"),
                failure_source=result.get("failure_source"),
            )

    if task.simulation.get("require_distinct_variant_outputs") and len(serial_outputs) > 1:
        unique = {text for text in serial_outputs.values()}
        if len(unique) == 1:
            return result_payload(
                FAIL,
                "all simulation variants produced identical serial output",
                {**metrics, "normalized_serial_outputs": serial_outputs},
            )
        # Cosmetic text differences are not enough: the measured values must
        # differ across variants, or the firmware is not reading the sensor.
        from .serial import extract_floats

        numeric_signatures = {
            current_id: tuple(extract_floats(text)) for current_id, text in serial_outputs.items()
        }
        # Text-only outputs (no numbers in any variant) are already covered by
        # the text comparison above; the numeric backstop only applies when at
        # least one variant emits numbers.
        if any(numeric_signatures.values()) and len(set(numeric_signatures.values())) == 1:
            return result_payload(
                FAIL,
                "all simulation variants produced identical numeric outputs",
                {**metrics, "numeric_signatures": {k: list(v) for k, v in numeric_signatures.items()}},
            )

    return result_payload(PASS, "all simulation variants passed", metrics)


def variant_id(variant: dict[str, Any]) -> str:
    return sanitize_variant_id(str(variant.get("id") or "variant"))


def variant_scenario_override(variant: dict[str, Any] | None) -> dict[str, Any] | None:
    if variant is None:
        return None
    scenario = variant.get("scenario")
    return scenario if isinstance(scenario, dict) else None


def paths_for_variant(
    paths: CasePaths, current_id: str, variant: dict[str, Any] | None = None
) -> CasePaths:
    variant_dir = paths.case_dir / "artifacts" / "variants" / current_id
    return replace(
        paths,
        diagram=variant_dir / "diagram.json",
        vcd=(paths.case_dir / "artifacts" / "logic" / f"{current_id}.vcd" if paths.vcd else None),
        scenario=(
            variant_dir / "scenario.yaml"
            if variant_scenario_override(variant) is not None
            else paths.scenario
        ),
        serial_log=(
            paths.case_dir / "artifacts" / "serial" / f"{current_id}.serial.log"
            if paths.serial_log
            else None
        ),
    )


def write_variant_diagram(base_diagram: Path, output_diagram: Path, variant: dict[str, Any]) -> None:
    diagram = json.loads(base_diagram.read_text(encoding="utf-8"))
    patched = apply_variant_attrs(diagram, variant.get("attrs") or {})
    write_diagram(output_diagram, patched)


def apply_variant_attrs(diagram: dict[str, Any], attrs_by_part: dict[str, Any]) -> dict[str, Any]:
    patched = deepcopy(diagram)
    parts = {
        str(part.get("id")): part
        for part in patched.get("parts", [])
        if isinstance(part, dict) and part.get("id") is not None
    }
    for part_id, attrs in attrs_by_part.items():
        if part_id not in parts:
            raise CaseConfigError(f"simulation variant references unknown part id: {part_id}")
        if not isinstance(attrs, dict):
            raise CaseConfigError(f"simulation variant attrs for {part_id} must be a mapping")
        part_attrs = dict(parts[part_id].get("attrs") or {})
        part_attrs.update({key: str(value) for key, value in attrs.items()})
        parts[part_id]["attrs"] = part_attrs
    return patched


def task_for_variant(task: TaskConfig, variant: dict[str, Any]) -> TaskConfig:
    data = deepcopy(task.data)
    if isinstance(variant.get("validator"), dict):
        data["validator"] = deep_merge(data.get("validator") or {}, variant["validator"])
    scenario_override = variant_scenario_override(variant)
    if scenario_override is not None:
        # Full replacement, not a merge: positionally merging stimulus timelines
        # would silently produce hybrid scenarios.
        data["scenario"] = deepcopy(scenario_override)
    data["active_simulation_variant"] = variant
    return TaskConfig(path=task.path, data=data)


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = deepcopy(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged[key], value) if key in merged else deepcopy(value)
        return merged
    if isinstance(base, list) and isinstance(override, list):
        merged = deepcopy(base)
        for index, value in enumerate(override):
            if index < len(merged):
                merged[index] = deep_merge(merged[index], value)
            else:
                merged.append(deepcopy(value))
        return merged
    return deepcopy(override)


def normalize_serial_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def clean_build_dir(paths: CasePaths) -> None:
    """Remove any previous build output so stale firmware can never be reused."""

    build_dir = paths.build_dir.resolve()
    case_dir = paths.case_dir.resolve()
    try:
        build_dir.relative_to(case_dir)
    except ValueError:
        # build_dir comes verbatim from case.yaml/case.json; never rmtree a
        # path that escapes the case directory.
        raise CaseConfigError(
            f"build dir must be inside the case dir: {build_dir} (case dir: {case_dir})"
        )
    if build_dir == case_dir:
        raise CaseConfigError(f"build dir must not be the case dir itself: {build_dir}")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)


def ensure_firmware_outputs(paths: CasePaths) -> None:
    firmware_hex, firmware_elf = expected_firmware_paths(paths)
    missing = [path for path in (firmware_hex, firmware_elf) if not path.exists()]
    if missing:
        normalize_firmware_outputs(paths)
        missing = [path for path in (firmware_hex, firmware_elf) if not path.exists()]
    # A genuine compile error is already raised as COMPILE_FAIL by run_checked
    # (arduino-cli exits non-zero). Reaching here means compilation succeeded but
    # the expected binary is absent or empty, which is a toolchain/artifact
    # problem, not the submission's compile failure. Classify it as an artifact
    # failure (-> IF) so it is never charged against the model as CF.
    if missing:
        names = ", ".join(str(path) for path in missing)
        raise BuildSimulationError(
            f"firmware binary artifact(s) missing after compile: {names}",
            classification=SIM_OUTPUT_FAIL,
            failure_stage=STAGE_SIM_OUTPUT,
            failure_source=SOURCE_ARTIFACT,
        )
    for path in (firmware_hex, firmware_elf):
        if path.stat().st_size == 0:
            raise BuildSimulationError(
                f"firmware binary artifact is empty: {path}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
                failure_source=SOURCE_ARTIFACT,
            )


def normalize_firmware_outputs(paths: CasePaths) -> None:
    """Relocate freshly compiled firmware into the expected artifact paths.

    Only binaries whose name matches the current sketch stem exactly and that
    live inside the current build dir are accepted; anything else (wrong-stem
    leftovers, files outside the build tree) is ignored so it can never be
    promoted to a validated artifact.
    """

    expected_image, expected_elf = expected_firmware_paths(paths)
    candidates = [
        paths.build_dir / f"{paths.sketch_name}.ino{paths.firmware_extension}",
        paths.build_dir / f"{paths.sketch_name}.ino.elf",
        *paths.build_dir.rglob(f"{paths.sketch_name}.ino{paths.firmware_extension}"),
        *paths.build_dir.rglob(f"{paths.sketch_name}.ino.elf"),
    ]
    for expected in (expected_image, expected_elf):
        if expected.exists():
            continue
        same_name = [
            candidate
            for candidate in candidates
            if candidate.name == expected.name and candidate.exists() and candidate != expected
        ]
        if same_name:
            expected.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(same_name[0], expected)


def ensure_existing_outputs(task: TaskConfig, paths: CasePaths) -> None:
    if task.requires_vcd:
        if paths.vcd is None or not paths.vcd.exists():
            raise BuildSimulationError(
                f"VCD not found: {paths.vcd}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
                failure_source=SOURCE_ARTIFACT,
            )
        if paths.vcd.stat().st_size == 0:
            raise BuildSimulationError(
                f"VCD is empty: {paths.vcd}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
                failure_source=SOURCE_ARTIFACT,
            )
    if task.requires_serial_log:
        if paths.serial_log is None or not paths.serial_log.exists():
            raise BuildSimulationError(
                f"serial log not found: {paths.serial_log}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
                failure_source=SOURCE_ARTIFACT,
            )
        if paths.serial_log.stat().st_size == 0:
            raise BuildSimulationError(
                f"serial log is empty: {paths.serial_log}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
                failure_source=SOURCE_ARTIFACT,
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
    command_failure_source: str,
    infra_failure_source: str,
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
            failure_source=infra_failure_source,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildSimulationError(
            f"{stage} timed out after {timeout_s:.1f}s",
            classification=command_failure_classification,
            failure_stage=command_failure_stage,
            failure_source=command_failure_source,
        ) from exc
    except OSError as exc:
        raise BuildSimulationError(
            f"{stage} failed: {exc}",
            classification=infra_failure_classification,
            failure_stage=infra_failure_stage,
            failure_source=infra_failure_source,
        ) from exc

    if completed.returncode != 0:
        raise BuildSimulationError(
            f"{stage} failed with exit code {completed.returncode}: {short_process_output(completed)}",
            classification=command_failure_classification,
            failure_stage=command_failure_stage,
            failure_source=command_failure_source,
        )


def write_verification(
    task: TaskConfig,
    paths: CasePaths,
    result: dict[str, Any],
    *,
    command: str,
    arduino_cli: str = "arduino-cli",
    wokwi_cli: str = "wokwi-cli",
) -> Path:
    tool_versions = current_tool_versions(arduino_cli=arduino_cli, wokwi_cli=wokwi_cli)
    manifest = {
        "manifest_version": 2,
        "task_id": task.task_id,
        "case_id": paths.case_id,
        "command": command,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "arduino_cli_version": tool_versions["arduino_cli_version"],
        "wokwi_cli_version": tool_versions["wokwi_cli_version"],
        "sketch_path": relative_to(paths.sketch, paths.case_dir),
        "sketch_hash": hash_path(paths.sketch),
        "diagram_path": relative_to(paths.diagram, paths.case_dir),
        "diagram_hash": hash_file(paths.diagram),
        "scenario_path": relative_to(paths.scenario, paths.case_dir) if paths.scenario else None,
        "scenario_hash": hash_file(paths.scenario) if paths.scenario else None,
        "firmware_image": relative_to(paths.firmware_image, paths.case_dir),
        "firmware_image_hash": hash_file(paths.firmware_image),
        "firmware_hex": relative_to(paths.firmware_hex, paths.case_dir),
        "firmware_hex_hash": hash_file(paths.firmware_hex),
        "firmware_elf": relative_to(paths.firmware_elf, paths.case_dir),
        "firmware_elf_hash": hash_file(paths.firmware_elf),
        "vcd_path": relative_to(paths.vcd, paths.case_dir) if paths.vcd else None,
        "vcd_hash": hash_file(paths.vcd) if paths.vcd else None,
        "serial_log_path": relative_to(paths.serial_log, paths.case_dir) if paths.serial_log else None,
        "serial_log_hash": hash_file(paths.serial_log) if paths.serial_log else None,
        "result": result.get("result"),
        "classification": result.get("classification"),
        "failure_stage": result.get("failure_stage"),
        "failure_source": result.get("failure_source"),
        "reason": result.get("reason"),
        "metrics": result.get("metrics", {}),
    }
    if task.simulation_variants:
        variant_results = {
            entry.get("id"): entry
            for entry in (result.get("metrics", {}).get("variants") or [])
            if isinstance(entry, dict)
        }
        manifest["variants"] = []
        for variant in task.simulation_variants:
            sanitized = variant_id(variant)
            variant_paths = paths_for_variant(paths, sanitized, variant)
            has_scenario_override = variant_scenario_override(variant) is not None
            manifest["variants"].append(
                {
                    "id": variant.get("id"),
                    "sanitized_id": sanitized,
                    "attrs": variant.get("attrs") or {},
                    "diagram_path": relative_to(variant_paths.diagram, paths.case_dir),
                    "diagram_hash": hash_file(variant_paths.diagram),
                    "scenario_path": (
                        relative_to(variant_paths.scenario, paths.case_dir)
                        if has_scenario_override and variant_paths.scenario
                        else None
                    ),
                    "scenario_hash": (
                        hash_file(variant_paths.scenario) if has_scenario_override else None
                    ),
                    "vcd_path": relative_to(variant_paths.vcd, paths.case_dir) if variant_paths.vcd else None,
                    "vcd_hash": hash_file(variant_paths.vcd) if variant_paths.vcd else None,
                    "serial_log_path": (
                        relative_to(variant_paths.serial_log, paths.case_dir)
                        if variant_paths.serial_log
                        else None
                    ),
                    "serial_log_hash": hash_file(variant_paths.serial_log) if variant_paths.serial_log else None,
                    "result": variant_results.get(sanitized, {}).get("result"),
                }
            )
    path = paths.case_dir / "artifacts" / "verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def artifact_provenance_error(message: str) -> BuildSimulationError:
    return BuildSimulationError(
        message,
        classification=SIM_OUTPUT_FAIL,
        failure_stage=STAGE_SIM_OUTPUT,
        failure_source=SOURCE_ARTIFACT,
    )


def validate_existing_artifact_manifest(
    task: TaskConfig,
    paths: CasePaths,
    *,
    ignore_vcd: bool = False,
    arduino_cli: str = "arduino-cli",
    wokwi_cli: str = "wokwi-cli",
    enforce_tool_versions: bool = True,
) -> None:
    """Require existing artifacts to match the verification manifest.

    Without this check, --use-existing-artifacts would validate whatever
    artifacts happen to be on disk, even ones produced from a different sketch,
    diagram, or scenario. Any mismatch is an artifact problem (-> IF), never a
    behavior judgment about the submission. Pass --allow-unverified-artifacts
    to skip this (deliberate inspection of arbitrary artifacts).
    """

    manifest_path = paths.case_dir / "artifacts" / "verification.json"
    if not manifest_path.exists():
        raise artifact_provenance_error(
            f"no verification manifest at {manifest_path}; existing artifacts have unknown provenance "
            "(rerun the full pipeline or pass --allow-unverified-artifacts)"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise artifact_provenance_error(f"verification manifest is unreadable: {exc}")
    if not isinstance(manifest, dict):
        raise artifact_provenance_error("verification manifest is not a JSON object")

    if manifest.get("task_id") != task.task_id:
        raise artifact_provenance_error(
            f"verification manifest belongs to task {manifest.get('task_id')!r}, not {task.task_id!r}"
        )
    if manifest.get("case_id") != paths.case_id:
        raise artifact_provenance_error(
            f"verification manifest belongs to case {manifest.get('case_id')!r}, not {paths.case_id!r}"
        )
    if enforce_tool_versions:
        validate_manifest_tool_versions(manifest, arduino_cli=arduino_cli, wokwi_cli=wokwi_cli)

    checks: list[tuple[str, str | None, str | None]] = [
        ("sketch", manifest.get("sketch_hash"), hash_path(paths.sketch)),
        ("diagram", manifest.get("diagram_hash"), hash_file(paths.diagram)),
        (
            "firmware image",
            manifest.get("firmware_image_hash", manifest.get("firmware_hex_hash")),
            hash_file(paths.firmware_image),
        ),
        ("firmware elf", manifest.get("firmware_elf_hash"), hash_file(paths.firmware_elf)),
    ]
    if paths.scenario:
        checks.append(("scenario", manifest.get("scenario_hash"), hash_file(paths.scenario)))
    if task.simulation_variants:
        manifest_variants = {
            entry.get("sanitized_id"): entry
            for entry in manifest.get("variants") or []
            if isinstance(entry, dict)
        }
        for variant in task.simulation_variants:
            sanitized = variant_id(variant)
            entry = manifest_variants.get(sanitized)
            if entry is None:
                raise artifact_provenance_error(
                    f"verification manifest has no record for variant {sanitized!r}"
                )
            variant_paths = paths_for_variant(paths, sanitized, variant)
            checks.append(
                (f"variant {sanitized} diagram", entry.get("diagram_hash"), hash_file(variant_paths.diagram))
            )
            if variant_scenario_override(variant) is not None and variant_paths.scenario:
                checks.append(
                    (
                        f"variant {sanitized} scenario",
                        entry.get("scenario_hash"),
                        hash_file(variant_paths.scenario),
                    )
                )
            if variant_paths.serial_log:
                checks.append(
                    (
                        f"variant {sanitized} serial log",
                        entry.get("serial_log_hash"),
                        hash_file(variant_paths.serial_log),
                    )
                )
            if variant_paths.vcd and not ignore_vcd:
                checks.append(
                    (f"variant {sanitized} VCD", entry.get("vcd_hash"), hash_file(variant_paths.vcd))
                )
    else:
        if paths.serial_log:
            checks.append(("serial log", manifest.get("serial_log_hash"), hash_file(paths.serial_log)))
        # ignore_vcd: --archived-vcd deliberately substitutes an archived VCD,
        # so its hash will not match the manifest's current-output hash.
        if paths.vcd and not ignore_vcd:
            checks.append(("VCD", manifest.get("vcd_hash"), hash_file(paths.vcd)))

    for label, recorded, current in checks:
        if recorded is None:
            raise artifact_provenance_error(
                f"verification manifest has no recorded {label} hash; regenerate artifacts with a full run"
            )
        if recorded != current:
            raise artifact_provenance_error(
                f"{label} does not match the verification manifest (recorded {recorded[:12]}..., "
                f"current {(current or 'missing')[:12]}...); artifacts were not produced from these inputs"
            )


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


def tool_versions_path() -> Path:
    return Path(__file__).with_name("tool_versions.yaml")


def pinned_tool_versions() -> dict[str, str | None]:
    try:
        data = yaml.safe_load(tool_versions_path().read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "arduino_cli_version": data.get("arduino_cli_version"),
        "wokwi_cli_version": data.get("wokwi_cli_version"),
    }


def current_tool_versions(
    *,
    arduino_cli: str = "arduino-cli",
    wokwi_cli: str = "wokwi-cli",
) -> dict[str, str | None]:
    return {
        "arduino_cli_version": command_version(arduino_cli, "version"),
        "wokwi_cli_version": command_version(wokwi_cli, "--version"),
    }


def tool_version_report(
    *,
    arduino_cli: str = "arduino-cli",
    wokwi_cli: str = "wokwi-cli",
) -> dict[str, Any]:
    expected = pinned_tool_versions()
    actual = current_tool_versions(arduino_cli=arduino_cli, wokwi_cli=wokwi_cli)
    mismatches = []
    for key, label in (
        ("arduino_cli_version", "arduino-cli"),
        ("wokwi_cli_version", "wokwi-cli"),
    ):
        if expected.get(key) != actual.get(key):
            mismatches.append(
                {
                    "tool": label,
                    "expected": expected.get(key),
                    "actual": actual.get(key),
                }
            )
    return {
        "ok": not mismatches,
        "expected": expected,
        "actual": actual,
        "mismatches": mismatches,
    }


def tool_version_mismatch_error(report: dict[str, Any]) -> BuildSimulationError:
    details = "; ".join(
        f"{item['tool']} expected {item['expected']!r}, got {item['actual']!r}"
        for item in report.get("mismatches", [])
    )
    return BuildSimulationError(
        f"tool version mismatch: {details or 'unknown mismatch'}",
        classification=SIM_INFRA_FAIL,
        failure_stage=STAGE_SIM_INFRA,
        failure_source=SOURCE_ENVIRONMENT,
    )


def ensure_tool_versions_compatible(
    *,
    arduino_cli: str = "arduino-cli",
    wokwi_cli: str = "wokwi-cli",
) -> dict[str, Any]:
    report = tool_version_report(arduino_cli=arduino_cli, wokwi_cli=wokwi_cli)
    if not report["ok"]:
        raise tool_version_mismatch_error(report)
    return report


def validate_manifest_tool_versions(
    manifest: dict[str, Any],
    *,
    arduino_cli: str,
    wokwi_cli: str,
) -> None:
    current = current_tool_versions(arduino_cli=arduino_cli, wokwi_cli=wokwi_cli)
    for key, label in (
        ("arduino_cli_version", "arduino-cli"),
        ("wokwi_cli_version", "wokwi-cli"),
    ):
        recorded = manifest.get(key)
        actual = current.get(key)
        if recorded != actual:
            raise artifact_provenance_error(
                f"{label} version does not match the verification manifest "
                f"(recorded {recorded!r}, current {actual!r}); rerun the full pipeline"
            )


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
    advanced = advanced_example_sketch(task)
    if advanced:
        return advanced
    examples = {
        "blink_led_1hz": blink_1hz_example,
        "blink_two_leds": BLINK_TWO_LEDS,
        "buzzer_doorbell": BUZZER_DOORBELL,
        "button_status_display": BUTTON_STATUS_DISPLAY,
        "button_status_count": button_status_count_example,
        "button_press_debounce": BUTTON_PRESS_DEBOUNCE,
        "sensor_pir_human_motion": SENSOR_PIR_HUMAN_MOTION,
        "tmp36_read": tmp36_read_example,
    }
    example = examples.get(task.task_id)
    if callable(example):
        return example(task)
    return example or "void setup() {}\nvoid loop() {}\n"


def advanced_example_sketch(task: TaskConfig) -> str | None:
    sensor_serial_examples = {
        "dht11_read": dht22_serial_example,
        "ds1307_rtc": ds1307_serial_example,
        "mpu6050_read_i2c": mpu6050_serial_example,
        "hcsr04_find_distance": hcsr04_serial_example,
        "step_counter_print": step_counter_example,
        "bme280_read_spi": bme280_spi_example,
    }
    if task.task_id in sensor_serial_examples:
        return sensor_serial_examples[task.task_id]()
    if task.task_id == "bme280_read_i2c":
        return bme280_i2c_example(task)

    lcd_lines = {
        "lcd1602_display_hello_world": ("  Hello World", ""),
    }
    lcd_sensor_examples = {
        "dht11_read_button_display": dht22_lcd_example,
        "mpu6050_read_button_display": mpu6050_lcd_example,
        "mpu6050_read_periodic_display": mpu6050_lcd_example,
        "sensor_water_level_display": water_level_lcd_example,
        "tmp36_read_button_display": tmp36_button_lcd_example,
        "reaction_timer_display": reaction_timer_lcd_example,
    }
    if task.task_id in lcd_sensor_examples:
        return lcd_sensor_examples[task.task_id](button="button" in task.task_id)
    if task.task_id in lcd_lines:
        return lcd_example(*lcd_lines[task.task_id], task_id=task.task_id)
    if task.task_id == "tmp36_read_periodic_display":
        return lcd_scrolling_temperature_example()

    outputs = {
        "tilt_detection_alarm": digital_follow_example(input_pin="14", output_pin="13"),
        # Wokwi photoresistor maps brighter light -> lower ADC (bright~169, dark~1015).
        # A nightlight lights when DARK, i.e. when the reading is ABOVE the threshold,
        # so invert=False (LED on when analogRead > threshold). Verified live.
        "photoresistor_nightlight": analog_threshold_led_example(analog_pin="A2", output_pin="3", threshold=400, invert=False),
        "ds18b20_heat_alarm": heat_alarm_example(),
        "clap_switch": clap_switch_example(),
        "hcsr501_motion_alarm": digital_follow_example(input_pin="18", output_pin="3"),
        "parking_sensor": parking_sensor_example(led_pin="3", buzzer_pin="2"),
        "reverse_parking_sensor": reverse_parking_example(buzzer_pin="3"),
        "rotary_encoder": rotary_encoder_example(),
        "16key_keypad": keypad_scan_example(),
        "safebox": safebox_example(display=False),
        "safebox_display": safebox_example(display=True),
        "lcd1602_auto_brightness_control": analog_pwm_example(analog_pin="A2", output_pin="10"),
        "buzzer_toggle_led_freq": button_led_frequency_example(),
        "buzzer_laser_tripwire": laser_tripwire_example(),
        "joystick_buzzer_pitch": joystick_pitch_example(),
    }
    return outputs.get(task.task_id)


def fixture_pin(task: TaskConfig, key: str, default_key: str | None = None) -> str:
    pins = task.fixture.get("pins", {}) if isinstance(task.fixture, dict) else {}
    fallback = task.board_profile.default_pins[default_key or key]
    return str(pins.get(key, fallback))


def blink_1hz_example(task: TaskConfig) -> str:
    pin = fixture_pin(task, "led")
    return f"""\
const int LED_PIN = {pin};
unsigned long lastToggleMs = 0;
bool ledState = LOW;

void setup() {{
  pinMode(LED_PIN, OUTPUT);
}}

void loop() {{
  unsigned long now = millis();
  if (now - lastToggleMs >= 500) {{
    lastToggleMs += 500;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
  }}
}}
"""


def button_status_count_example(task: TaskConfig) -> str:
    pin = fixture_pin(task, "button")
    return f"""\
const int BUTTON_PIN = {pin};
bool wasPressed = false;
int count = 0;

void setup() {{
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT);
}}

void loop() {{
  bool pressed = digitalRead(BUTTON_PIN) == HIGH;
  if (pressed && !wasPressed) {{
    count++;
    Serial.println(count);
  }}
  wasPressed = pressed;
  delay(5);
}}
"""


def tmp36_read_example(task: TaskConfig) -> str:
    pin = fixture_pin(task, "analog")
    profile = task.board_profile
    return f"""\
const int TMP36_PIN = {pin};

void setup() {{
  Serial.begin(115200);
}}

void loop() {{
  int raw = analogRead(TMP36_PIN);
  float voltage = raw * ({profile.voltage:.6g} / {float(profile.adc_max):.1f});
  float celsius = (voltage - 0.5) * 100.0;
  Serial.println(celsius, 1);
  delay(100);
}}
"""


def dht22_serial_example() -> str:
    return dht22_reader_source(pin="14") + """\
void setup() {
  Serial.begin(115200);
  pinMode(DHT_PIN, INPUT_PULLUP);
}

void loop() {
  float temperature = 0;
  float humidity = 0;
  if (readDht22(temperature, humidity)) {
    Serial.print("Temperature: ");
    Serial.print(temperature, 1);
    Serial.print(" C Humidity: ");
    Serial.print(humidity, 1);
    Serial.println(" %");
  }
  delay(250);
}
"""


def ds1307_serial_example() -> str:
    return """\
#include <Wire.h>

byte bcdToDec(byte value) { return (value >> 4) * 10 + (value & 0x0F); }

void setup() {
  Serial.begin(115200);
  Wire.begin();
}

void loop() {
  Wire.beginTransmission(0x68);
  Wire.write(0);
  Wire.endTransmission();
  Wire.requestFrom(0x68, 7);
  if (Wire.available() >= 7) {
    byte second = bcdToDec(Wire.read() & 0x7F);
    byte minute = bcdToDec(Wire.read());
    byte hour = bcdToDec(Wire.read() & 0x3F);
    Wire.read();
    byte day = bcdToDec(Wire.read());
    byte month = bcdToDec(Wire.read());
    int year = 2000 + bcdToDec(Wire.read());
    char buf[24];
    sprintf(buf, "%04d/%02d/%02d %02d:%02d:%02d", year, month, day, hour, minute, second);
    Serial.println(buf);
  }
  delay(500);
}
"""


def mpu6050_serial_example() -> str:
    return mpu6050_reader_source() + """\
void setup() {
  Serial.begin(115200);
  mpuBegin();
}

void loop() {
  int16_t ax, ay, az, gx, gy, gz;
  readMpu(ax, ay, az, gx, gy, gz);
  Serial.print("Accel: ");
  Serial.print(ax);
  Serial.print(" ");
  Serial.print(ay);
  Serial.print(" ");
  Serial.print(az);
  Serial.print(" Gyro: ");
  Serial.print(gx);
  Serial.print(" ");
  Serial.print(gy);
  Serial.print(" ");
  Serial.println(gz);
  delay(250);
}
"""


def step_counter_example() -> str:
    return mpu6050_reader_source() + """\
const float STEP_HIGH_G = 1.5;
const float STEP_LOW_G = 1.2;
int steps = 0;
bool above = false;
unsigned long lastStepMs = 0;

void setup() {
  Serial.begin(115200);
  mpuBegin();
}

void loop() {
  int16_t ax, ay, az, gx, gy, gz;
  readMpu(ax, ay, az, gx, gy, gz);
  float x = ax / 16384.0;
  float y = ay / 16384.0;
  float z = az / 16384.0;
  float magnitude = sqrt(x * x + y * y + z * z);
  unsigned long now = millis();
  if (!above && magnitude >= STEP_HIGH_G && now - lastStepMs > 120) {
    above = true;
    steps++;
    lastStepMs = now;
    Serial.print("Steps: ");
    Serial.println(steps);
  } else if (above && magnitude <= STEP_LOW_G) {
    above = false;
  }
  delay(20);
}
"""


def rotary_encoder_example() -> str:
    return """\
const int PIN_CLK = 2;
const int PIN_DT = 3;
const int PIN_SW = 4;
// Quadrature transition table indexed by (previous << 2) | current, where each
// 2-bit state is (CLK << 1) | DT. Valid edges contribute +1 (CW) or -1 (CCW).
const int8_t QUAD[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
int lastState = 0;
int subStep = 0;
long position = 0;

int readState() {
  return (digitalRead(PIN_CLK) << 1) | digitalRead(PIN_DT);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_CLK, INPUT_PULLUP);
  pinMode(PIN_DT, INPUT_PULLUP);
  pinMode(PIN_SW, INPUT_PULLUP);
  lastState = readState();
}

void loop() {
  int state = readState();
  if (state != lastState) {
    subStep += QUAD[(lastState << 2) | state];
    lastState = state;
    if (subStep >= 4) {
      subStep = 0;
      position++;
      Serial.print("Position: ");
      Serial.print(position);
      Serial.println(" Direction: CW");
    } else if (subStep <= -4) {
      subStep = 0;
      position--;
      Serial.print("Position: ");
      Serial.print(position);
      Serial.println(" Direction: CCW");
    }
  }
}
"""


def keypad_reader_source(row_pins: list[int], col_pins: list[int]) -> str:
    rows = ", ".join(str(pin) for pin in row_pins)
    cols = ", ".join(str(pin) for pin in col_pins)
    return f"""\
const byte ROWS = 4;
const byte COLS = 4;
const char KEYS[ROWS][COLS] = {{
  {{'1', '2', '3', 'A'}},
  {{'4', '5', '6', 'B'}},
  {{'7', '8', '9', 'C'}},
  {{'*', '0', '#', 'D'}}
}};
const byte ROW_PINS[ROWS] = {{{rows}}};
const byte COL_PINS[COLS] = {{{cols}}};

void keypadBegin() {{
  for (byte r = 0; r < ROWS; r++) pinMode(ROW_PINS[r], INPUT_PULLUP);
  for (byte c = 0; c < COLS; c++) pinMode(COL_PINS[c], INPUT);
}}

char scanKeypad() {{
  char found = 0;
  for (byte c = 0; c < COLS; c++) {{
    pinMode(COL_PINS[c], OUTPUT);
    digitalWrite(COL_PINS[c], LOW);
    for (byte r = 0; r < ROWS; r++) {{
      if (digitalRead(ROW_PINS[r]) == LOW) found = KEYS[r][c];
    }}
    pinMode(COL_PINS[c], INPUT);
  }}
  return found;
}}

"""


def keypad_scan_example() -> str:
    return keypad_reader_source([9, 8, 7, 6], [5, 4, 3, 2]) + """\
char lastKey = 0;

void setup() {
  Serial.begin(115200);
  keypadBegin();
}

void loop() {
  char key = scanKeypad();
  if (key && key != lastKey) {
    Serial.print("Key: ");
    Serial.println(key);
  }
  lastKey = key;
  delay(5);
}
"""


def hcsr04_serial_example() -> str:
    return hcsr04_reader_source() + """\
void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
}

void loop() {
  long distance = readDistanceCm();
  Serial.print("Distance: ");
  Serial.print(distance);
  Serial.println(" cm");
  delay(250);
}
"""


def bme280_i2c_example(task: TaskConfig) -> str:
    sda = fixture_pin(task, "sda", "i2c_sda")
    scl = fixture_pin(task, "scl", "i2c_scl")
    wire_begin = "Wire.begin();"
    if task.platform == "esp32":
        wire_begin = f"Wire.begin({sda}, {scl});"
    return """\
#include <Adafruit_BME280.h>
#include <Wire.h>

Adafruit_BME280 bme;

void setup() {
  Serial.begin(115200);
  WIRE_BEGIN
  if (!bme.begin(0x76)) {
    Serial.println("BME280 not found");
    while (true) {
      delay(100);
    }
  }
}

void loop() {
  Serial.print("Temperature: ");
  Serial.print(bme.readTemperature(), 1);
  Serial.print(" C Humidity: ");
  Serial.print(bme.readHumidity(), 1);
  Serial.print(" % Pressure: ");
  Serial.print(bme.readPressure(), 0);
  Serial.println(" Pa");
  delay(500);
}
""".replace("WIRE_BEGIN", wire_begin)


def bme280_spi_example() -> str:
    return """\
#include <Adafruit_BME280.h>

const int BME_CS = 21;
const int BME_MOSI = 36;
const int BME_MISO = 37;
const int BME_SCK = 35;

Adafruit_BME280 bme(BME_CS, BME_MOSI, BME_MISO, BME_SCK);

void setup() {
  Serial.begin(115200);
  if (!bme.begin()) {
    Serial.println("BME280 not found");
    while (true) {
      delay(100);
    }
  }
}

void loop() {
  Serial.print("Temperature: ");
  Serial.print(bme.readTemperature(), 1);
  Serial.print(" C Humidity: ");
  Serial.print(bme.readHumidity(), 1);
  Serial.print(" % Pressure: ");
  Serial.print(bme.readPressure(), 0);
  Serial.println(" Pa");
  delay(500);
}
"""


def lcd_example(line1: str, line2: str, *, task_id: str) -> str:
    extra = ""
    if "button" in task_id or task_id == "reaction_timer_display":
        extra = "volatile bool requested = false;\nvoid onButton(){ requested = true; }\n"
    setup_extra = "  pinMode(2, INPUT);\n  attachInterrupt(digitalPinToInterrupt(2), onButton, RISING);\n" if extra else ""
    includes = ""
    if "mpu6050" in task_id:
        includes = "#include <Wire.h>\n"
        setup_extra += "  Wire.begin();\n  unsigned long sampleTime = millis();\n"
    if task_id == "safebox_display":
        setup_extra += "  pinMode(13, OUTPUT);\n  digitalWrite(13, HIGH);\n"
    return f"""\
{includes}
{lcd_driver_source()}
{extra}
void show() {{
  lcdClear();
  lcdSetCursor(0, 0);
  lcdPrint("{line1[:16]}");
  lcdSetCursor(0, 1);
  lcdPrint("{line2[:16]}");
}}

void setup() {{
{setup_extra}  lcdBegin();
  show();
}}

void loop() {{
  show();
  delay(250);
}}
"""


def lcd_scrolling_temperature_example() -> str:
    return lcd_driver_source() + """\
volatile bool resetRequested = false;
int counter = 1;

void onButton(){ resetRequested = true; }

void setup() {
  pinMode(2, INPUT);
  attachInterrupt(digitalPinToInterrupt(2), onButton, RISING);
  lcdBegin();
}

void loop() {
  if (resetRequested) { counter = 1; lcdClear(); resetRequested = false; }
  int raw = analogRead(A0);
  lcdClear();
  lcdSetCursor(0, 0);
  lcdPrint("Temp #");
  lcdPrintInt(counter++);
  lcdPrint(":");
  lcdSetCursor(0, 1);
  lcdPrintInt(raw);
  lcdPrint(" F");
  delay(1000);
}
"""


def lcd_driver_source() -> str:
    return """\
const int LCD_RS = 12;
const int LCD_E = 11;
const int LCD_D4 = 4;
const int LCD_D5 = 5;
const int LCD_D6 = 6;
const int LCD_D7 = 7;

void lcdPulse() {
  digitalWrite(LCD_E, HIGH);
  delayMicroseconds(1);
  digitalWrite(LCD_E, LOW);
  delayMicroseconds(50);
}

void lcdNibble(byte value) {
  digitalWrite(LCD_D4, value & 0x01);
  digitalWrite(LCD_D5, value & 0x02);
  digitalWrite(LCD_D6, value & 0x04);
  digitalWrite(LCD_D7, value & 0x08);
  lcdPulse();
}

void lcdWrite(byte value, bool rs) {
  digitalWrite(LCD_RS, rs ? HIGH : LOW);
  lcdNibble(value >> 4);
  lcdNibble(value & 0x0F);
}

void lcdCommand(byte value) {
  lcdWrite(value, false);
  if (value == 1) delay(2);
}

void lcdData(byte value) {
  lcdWrite(value, true);
}

void lcdBegin() {
  pinMode(LCD_RS, OUTPUT);
  pinMode(LCD_E, OUTPUT);
  pinMode(LCD_D4, OUTPUT);
  pinMode(LCD_D5, OUTPUT);
  pinMode(LCD_D6, OUTPUT);
  pinMode(LCD_D7, OUTPUT);
  delay(50);
  lcdCommand(0x28);
  lcdCommand(0x0C);
  lcdCommand(0x06);
  lcdCommand(0x01);
}

void lcdClear() { lcdCommand(0x01); }
void lcdSetCursor(byte col, byte row) { lcdCommand((row ? 0xC0 : 0x80) + col); }
void lcdPrint(const char *text) { while (*text) lcdData(*text++); }
void lcdPrintInt(int value) {
  char buf[12];
  itoa(value, buf, 10);
  lcdPrint(buf);
}
"""


def dht22_reader_source(*, pin: str) -> str:
    return f"""\
const int DHT_PIN = {pin};

bool expectPulse(int state, unsigned long timeout) {{
  unsigned long start = micros();
  while (digitalRead(DHT_PIN) == state) {{
    if (micros() - start > timeout) return false;
  }}
  return true;
}}

bool readDht22(float &temperature, float &humidity) {{
  uint8_t data[5] = {{0, 0, 0, 0, 0}};
  pinMode(DHT_PIN, OUTPUT);
  digitalWrite(DHT_PIN, LOW);
  delay(2);
  digitalWrite(DHT_PIN, HIGH);
  delayMicroseconds(30);
  pinMode(DHT_PIN, INPUT_PULLUP);
  if (!expectPulse(HIGH, 100)) return false;
  if (!expectPulse(LOW, 100)) return false;
  if (!expectPulse(HIGH, 100)) return false;
  for (int bit = 0; bit < 40; ++bit) {{
    if (!expectPulse(LOW, 80)) return false;
    unsigned long start = micros();
    if (!expectPulse(HIGH, 120)) return false;
    if (micros() - start > 45) data[bit / 8] |= (1 << (7 - (bit % 8)));
  }}
  uint8_t checksum = data[0] + data[1] + data[2] + data[3];
  if (checksum != data[4]) return false;
  humidity = ((data[0] << 8) | data[1]) / 10.0;
  int16_t rawTemp = ((data[2] & 0x7F) << 8) | data[3];
  temperature = rawTemp / 10.0;
  if (data[2] & 0x80) temperature = -temperature;
  return true;
}}

"""


def mpu6050_reader_source() -> str:
    return """\
#include <Wire.h>

void mpuBegin() {
  Wire.begin();
  Wire.beginTransmission(0x68);
  Wire.write(0x6B);
  Wire.write(0);
  Wire.endTransmission();
}

int16_t readWord() {
  int high = Wire.read();
  int low = Wire.read();
  return (int16_t)((high << 8) | low);
}

void readMpu(int16_t &ax, int16_t &ay, int16_t &az, int16_t &gx, int16_t &gy, int16_t &gz) {
  Wire.beginTransmission(0x68);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(0x68, 14);
  ax = readWord();
  ay = readWord();
  az = readWord();
  readWord();
  gx = readWord();
  gy = readWord();
  gz = readWord();
}

"""


def hcsr04_reader_source() -> str:
    return """\
const int TRIG_PIN = 9;
const int ECHO_PIN = 10;

long readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return -1;
  return duration / 58;
}

"""


def ds18b20_reader_source() -> str:
    return """\
const int ONE_WIRE_PIN = 4;

void oneWireLow(unsigned int us) {
  pinMode(ONE_WIRE_PIN, OUTPUT);
  digitalWrite(ONE_WIRE_PIN, LOW);
  delayMicroseconds(us);
}

void oneWireRelease(unsigned int us) {
  pinMode(ONE_WIRE_PIN, INPUT_PULLUP);
  delayMicroseconds(us);
}

bool oneWireReset() {
  oneWireLow(480);
  oneWireRelease(70);
  bool present = digitalRead(ONE_WIRE_PIN) == LOW;
  delayMicroseconds(410);
  return present;
}

void oneWireWriteBit(bool bitValue) {
  if (bitValue) {
    oneWireLow(6);
    oneWireRelease(64);
  } else {
    oneWireLow(60);
    oneWireRelease(10);
  }
}

bool oneWireReadBit() {
  oneWireLow(6);
  oneWireRelease(9);
  bool value = digitalRead(ONE_WIRE_PIN);
  delayMicroseconds(55);
  return value;
}

void oneWireWriteByte(byte value) {
  for (byte i = 0; i < 8; ++i) {
    oneWireWriteBit(value & 1);
    value >>= 1;
  }
}

byte oneWireReadByte() {
  byte value = 0;
  for (byte i = 0; i < 8; ++i) {
    if (oneWireReadBit()) value |= (1 << i);
  }
  return value;
}

float readDs18b20C() {
  if (!oneWireReset()) return -127.0;
  oneWireWriteByte(0xCC);
  oneWireWriteByte(0x44);
  delay(120);
  if (!oneWireReset()) return -127.0;
  oneWireWriteByte(0xCC);
  oneWireWriteByte(0xBE);
  byte lo = oneWireReadByte();
  byte hi = oneWireReadByte();
  int16_t raw = (int16_t)((hi << 8) | lo);
  return raw / 16.0;
}

"""


def dht22_lcd_example(*, button: bool) -> str:
    interrupt = "volatile bool requested = false;\nvoid onButton(){ requested = true; }\n" if button else ""
    setup_button = "  pinMode(2, INPUT);\n  attachInterrupt(digitalPinToInterrupt(2), onButton, RISING);\n" if button else ""
    guard = "  if (!requested) return;\n  requested = false;\n" if button else ""
    return dht22_reader_source(pin="3") + lcd_driver_source() + interrupt + f"""\
void setup() {{
{setup_button}  pinMode(DHT_PIN, INPUT_PULLUP);
  lcdBegin();
}}

void loop() {{
{guard}  float temperature = 0;
  float humidity = 0;
  if (readDht22(temperature, humidity)) {{
    lcdClear();
    lcdSetCursor(0, 0);
    lcdPrint("Temp: ");
    lcdPrintInt((int)(temperature + 0.5));
    lcdPrint("C");
    lcdSetCursor(0, 1);
    lcdPrint("RH: ");
    lcdPrintInt((int)(humidity + 0.5));
    lcdPrint("%");
  }}
  delay(250);
}}
"""


def mpu6050_lcd_example(*, button: bool) -> str:
    interrupt = "volatile bool requested = false;\nvoid onButton(){ requested = true; }\n" if button else ""
    setup_button = "  pinMode(2, INPUT);\n  attachInterrupt(digitalPinToInterrupt(2), onButton, RISING);\n" if button else ""
    guard = "  if (!requested) return;\n  requested = false;\n" if button else ""
    return mpu6050_reader_source() + lcd_driver_source() + interrupt + f"""\
void setup() {{
{setup_button}  mpuBegin();
  lcdBegin();
}}

void loop() {{
{guard}  int16_t ax, ay, az, gx, gy, gz;
  unsigned long sampleTime = millis();
  (void)sampleTime;
  readMpu(ax, ay, az, gx, gy, gz);
  lcdClear();
  lcdSetCursor(0, 0);
  lcdPrint("Accel:");
  lcdPrintInt(ax);
  lcdSetCursor(0, 1);
  lcdPrint("Gyro:");
  lcdPrintInt(gx);
  delay(250);
}}
"""


def water_level_lcd_example(*, button: bool = False) -> str:
    return lcd_driver_source() + """\
void setup() {
  lcdBegin();
}

void loop() {
  int raw = analogRead(A2);
  int bars = map(raw, 0, 1023, 0, 8);
  lcdClear();
  lcdSetCursor(0, 0);
  lcdPrint("Water Level");
  lcdSetCursor(0, 1);
  for (int i = 0; i < bars; ++i) lcdPrint("#");
  delay(250);
}
"""


def tmp36_button_lcd_example(*, button: bool) -> str:
    return lcd_driver_source() + """\
volatile bool requested = false;
void onButton(){ requested = true; }

void setup() {
  pinMode(2, INPUT);
  attachInterrupt(digitalPinToInterrupt(2), onButton, RISING);
  lcdBegin();
}

void loop() {
  if (!requested) return;
  requested = false;
  int raw = analogRead(A0);
  float voltage = raw * (5.0 / 1023.0);
  int fahrenheit = (int)((voltage - 0.5) * 100.0 * 9.0 / 5.0 + 32.0 + 0.5);
  lcdClear();
  lcdSetCursor(0, 0);
  lcdPrint("Temp: ");
  lcdPrintInt(fahrenheit);
  lcdPrint(" F");
  delay(250);
}
"""


def reaction_timer_lcd_example(*, button: bool) -> str:
    return lcd_driver_source() + """\
const int START_PIN = 2;
const int SHOCK_PIN = 3;
bool timing = false;
unsigned long startMs = 0;

void setup() {
  pinMode(START_PIN, INPUT);
  pinMode(SHOCK_PIN, INPUT);
  lcdBegin();
}

void loop() {
  if (digitalRead(START_PIN) && !timing) {
    timing = true;
    startMs = millis();
  }
  if (timing && digitalRead(SHOCK_PIN)) {
    unsigned long elapsed = millis() - startMs;
    timing = false;
    lcdClear();
    lcdSetCursor(0, 0);
    lcdPrint("Time: ");
    lcdPrintInt((int)elapsed);
    lcdPrint(" ms");
  }
  delay(10);
}
"""


def digital_follow_example(*, input_pin: str, output_pin: str) -> str:
    return f"""\
const int INPUT_PIN = {input_pin};
const int OUTPUT_PIN = {output_pin};
void setup() {{
  pinMode(INPUT_PIN, INPUT);
  pinMode(OUTPUT_PIN, OUTPUT);
}}
void loop() {{
  digitalWrite(OUTPUT_PIN, digitalRead(INPUT_PIN));
}}
"""


def analog_threshold_led_example(*, analog_pin: str, output_pin: str, threshold: int, invert: bool) -> str:
    op = "<" if invert else ">"
    return f"""\
void setup() {{
  pinMode({output_pin}, OUTPUT);
}}
void loop() {{
  int value = analogRead({analog_pin});
  digitalWrite({output_pin}, value {op} {threshold} ? HIGH : LOW);
}}
"""


def heat_alarm_example() -> str:
    return ds18b20_reader_source() + """\
void setup() {
  pinMode(2, OUTPUT);
  pinMode(3, OUTPUT);
}
void loop() {
  float temperature = readDs18b20C();
  bool hot = temperature > 30.0;
  digitalWrite(2, hot ? HIGH : LOW);
  if (hot) {
    digitalWrite(3, HIGH);
    delay(80);
    digitalWrite(3, LOW);
    delay(80);
  } else {
    digitalWrite(3, LOW);
    delay(80);
  }
}
"""


def clap_switch_example() -> str:
    return """\
const int SOUND_PIN = 7;
const int RELAY_PIN = 2;
bool relayState = false;
bool lastSound = false;
void setup(){ pinMode(SOUND_PIN, INPUT); pinMode(RELAY_PIN, OUTPUT); }
void loop(){
  bool sound = digitalRead(SOUND_PIN);
  if (sound && !lastSound) { relayState = !relayState; digitalWrite(RELAY_PIN, relayState); }
  lastSound = sound;
  delay(5);
}
"""


def parking_sensor_example(*, led_pin: str, buzzer_pin: str) -> str:
    return hcsr04_reader_source() + f"""\
void setup() {{ pinMode({led_pin}, OUTPUT); pinMode({buzzer_pin}, OUTPUT); pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT); }}
void loop() {{
  long distance = readDistanceCm();
  if (distance > 0 && distance < 80) {{
    digitalWrite({led_pin}, HIGH);
    tone({buzzer_pin}, distance < 40 ? 2000 : 1000);
  }} else {{
    digitalWrite({led_pin}, LOW);
    noTone({buzzer_pin});
  }}
  delay(60);
}}
"""


def reverse_parking_example(*, buzzer_pin: str) -> str:
    return hcsr04_reader_source() + f"""\
void setup() {{ pinMode({buzzer_pin}, OUTPUT); pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT); }}
void loop() {{
  long distance = readDistanceCm();
  if (distance > 0 && distance < 60) tone({buzzer_pin}, 1500);
  else if (distance > 0 && distance < 150) tone({buzzer_pin}, 700);
  else noTone({buzzer_pin});
  delay(60);
}}
"""


def safebox_example(*, display: bool) -> str:
    # The two safebox cases use different keypad pins: the no-display case keeps the
    # keypad on 9..6 / 5..2, while the display case moves it to 22..28 / 30..36 so it
    # does not collide with the LCD data pins (4..7).
    if display:
        keypad = keypad_reader_source([22, 24, 26, 28], [30, 32, 34, 36])
        return lcd_driver_source() + keypad + """\
const int RELAY_PIN = 13;
const char PASSWORD[] = "1234";
char entry[5] = "";
byte entryLen = 0;
char lastKey = 0;
bool unlocked = false;

void showStatus(const char *status) {
  lcdClear();
  lcdSetCursor(0, 0);
  lcdPrint("Input: ");
  lcdPrint(entry);
  lcdSetCursor(0, 1);
  lcdPrint("Status: ");
  lcdPrint(status);
}

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  keypadBegin();
  lcdBegin();
  showStatus("Enter");
}

void loop() {
  char key = scanKeypad();
  if (key && key != lastKey && !unlocked) {
    if (entryLen < 4) {
      entry[entryLen++] = key;
      entry[entryLen] = '\\0';
    }
    if (entryLen == 4) {
      if (strcmp(entry, PASSWORD) == 0) {
        unlocked = true;
        digitalWrite(RELAY_PIN, HIGH);
        showStatus("Success");
      } else {
        showStatus("Denied");
        entryLen = 0;
        entry[0] = '\\0';
      }
    } else {
      showStatus("Enter");
    }
  }
  lastKey = key;
  delay(5);
}
"""
    keypad = keypad_reader_source([9, 8, 7, 6], [5, 4, 3, 2])
    return keypad + """\
const int RELAY_PIN = 13;
const char PASSWORD[] = "1234";
char entry[5] = "";
byte entryLen = 0;
char lastKey = 0;
bool unlocked = false;

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  keypadBegin();
}

void loop() {
  char key = scanKeypad();
  if (key && key != lastKey && !unlocked) {
    if (entryLen < 4) {
      entry[entryLen++] = key;
      entry[entryLen] = '\\0';
    }
    if (entryLen == 4) {
      if (strcmp(entry, PASSWORD) == 0) {
        unlocked = true;
        digitalWrite(RELAY_PIN, HIGH);
      } else {
        entryLen = 0;
        entry[0] = '\\0';
      }
    }
  }
  lastKey = key;
  delay(5);
}
"""


def analog_pwm_example(*, analog_pin: str, output_pin: str) -> str:
    return f"""\
void setup() {{ pinMode({output_pin}, OUTPUT); }}
void loop() {{
  int value = analogRead({analog_pin});
  analogWrite({output_pin}, map(value, 0, 1023, 0, 255));
}}
"""


def button_led_frequency_example() -> str:
    return """\
const int BUTTON_PIN = 2;
const int BUZZER_PIN = 3;
const int LED_PIN = 4;
int mode = 0;
bool lastButton = false;
unsigned long lastToggle = 0;
bool ledState = false;
void setup(){ pinMode(BUTTON_PIN, INPUT); pinMode(BUZZER_PIN, OUTPUT); pinMode(LED_PIN, OUTPUT); attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), []{}, RISING); }
void loop(){
  bool pressed = digitalRead(BUTTON_PIN);
  if (pressed && !lastButton) { mode = (mode + 1) % 4; tone(BUZZER_PIN, 2000, 80); }
  lastButton = pressed;
  int interval = mode == 1 ? 500 : (mode == 2 ? 250 : (mode == 3 ? 125 : 0));
  if (interval == 0) { digitalWrite(LED_PIN, LOW); return; }
  if (millis() - lastToggle >= (unsigned long)interval) { lastToggle = millis(); ledState = !ledState; digitalWrite(LED_PIN, ledState); }
}
"""


def laser_tripwire_example() -> str:
    return """\
void setup(){ pinMode(8, OUTPUT); pinMode(3, OUTPUT); digitalWrite(8, HIGH); }
void loop(){
  int light = analogRead(A0);
  if (light < 400) tone(3, 1200);
  else noTone(3);
}
"""


def joystick_pitch_example() -> str:
    return """\
void setup(){ pinMode(3, OUTPUT); }
void loop(){
  int y = analogRead(A0);
  tone(3, map(y, 0, 1023, 200, 1800));
}
"""


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

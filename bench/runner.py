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
from . import renode


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
    firmware_kind: str = "arduino_image"
    vcd: Path | None = None
    scenario: Path | None = None
    serial_log: Path | None = None
    # Renode backend only: the generated monitor script. For Renode cases the
    # `diagram` field holds the .repl platform description (same provenance
    # and variant plumbing as Wokwi diagrams) and `wokwi_toml` is unused.
    resc: Path | None = None

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
    paths = case_paths_from_task(task, case_dir)

    scenario_data = generate_scenario(task)
    if paths.scenario:
        write_scenario(paths.scenario, scenario_data)

    if task.board_profile.backend == "renode":
        paths.diagram.parent.mkdir(parents=True, exist_ok=True)
        paths.diagram.write_text(renode.generate_repl(task), encoding="utf-8")
        write_case_resc(task, paths, scenario_data)
        write_case_yaml(task, paths)
        write_case_json(task, paths)
        ensure_sketch_files(task, paths.sketch)
        ensure_artifact_dirs(paths)
        renode.validate_renode_case(task, paths.diagram, paths.resc)
        return paths

    write_diagram(paths.diagram, generate_diagram(task))
    write_case_yaml(task, paths)
    write_case_json(task, paths)
    write_wokwi_toml(task, paths)
    ensure_custom_chip_artifacts(task, paths, root)
    ensure_sketch_files(task, paths.sketch)
    ensure_artifact_dirs(paths)
    validate_diagram_file(paths.diagram, task)
    return paths


def write_case_resc(
    task: TaskConfig,
    paths: CasePaths,
    scenario_data: dict[str, Any] | None,
    *,
    timeout_ms: int | None = None,
) -> None:
    if paths.resc is None:
        raise CaseConfigError(f"{task.task_id}: Renode case has no resc path")
    elf = expected_firmware_paths(paths)[1]
    text = renode.generate_resc(
        task,
        repl_relpath=relative_to(paths.diagram, paths.case_dir),
        elf_relpath=relative_to(elf, paths.case_dir),
        serial_relpath=(
            relative_to(paths.serial_log, paths.case_dir) if paths.serial_log else None
        ),
        vcd_abspath=str(paths.vcd.resolve()) if paths.vcd else None,
        scenario=scenario_data,
        timeout_ms=timeout_ms or int(task.simulation.get("timeout_ms", 5000)),
    )
    paths.resc.parent.mkdir(parents=True, exist_ok=True)
    paths.resc.write_text(text, encoding="utf-8")


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
            if not source.exists():
                source = root / "bench" / "chips" / str(chip["name"]) / relative.name
            if not source.exists():
                matches = sorted((root / "cases").glob(f"*/chips/{relative.name}"))
                if matches:
                    source = matches[0]
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
    is_renode = task.board_profile.backend == "renode"
    return CasePaths(
        task_id=task.task_id,
        case_id=task.case_id,
        case_dir=case_dir,
        sketch=sketch,
        diagram=case_dir / ("case.repl" if is_renode else "diagram.json"),
        wokwi_toml=case_dir / "wokwi.toml",
        build_dir=case_dir / "artifacts" / "build",
        fqbn=task.board.get("fqbn", DEFAULT_FQBN),
        firmware_extension=task.board_profile.firmware_extension,
        firmware_kind=task.board_profile.firmware_kind,
        vcd=(
            case_dir / "artifacts" / "logic" / ("renode.vcd" if is_renode else "wokwi.vcd")
            if task.requires_vcd
            else None
        ),
        scenario=scenario,
        serial_log=(
            case_dir / "artifacts" / "serial" / "serial.log"
            if task.requires_serial_log
            else None
        ),
        resc=(case_dir / "case.resc" if is_renode else None),
    )


def write_case_yaml(task: TaskConfig, paths: CasePaths) -> None:
    data: dict[str, Any] = {
        "task_id": task.task_id,
        "case_id": task.case_id,
        "board": task.board,
        "paths": case_manifest_paths(task, paths),
    }
    (paths.case_dir / "case.yaml").parent.mkdir(parents=True, exist_ok=True)
    (paths.case_dir / "case.yaml").write_text(to_yaml_text(data), encoding="utf-8")


def case_manifest_paths(task: TaskConfig, paths: CasePaths) -> dict[str, str]:
    entry: dict[str, str] = {
        "sketch": relative_to(paths.sketch, paths.case_dir),
        "diagram": relative_to(paths.diagram, paths.case_dir),
    }
    if task.board_profile.backend != "renode":
        entry["wokwi"] = relative_to(paths.wokwi_toml, paths.case_dir)
    entry["build"] = relative_to(paths.build_dir, paths.case_dir)
    if paths.vcd:
        entry["vcd"] = relative_to(paths.vcd, paths.case_dir)
    if paths.scenario:
        entry["scenario"] = relative_to(paths.scenario, paths.case_dir)
    if paths.serial_log:
        entry["serial_log"] = relative_to(paths.serial_log, paths.case_dir)
    if paths.resc:
        entry["resc"] = relative_to(paths.resc, paths.case_dir)
    return entry


def write_case_json(task: TaskConfig, paths: CasePaths) -> None:
    channels = task.fixture.get("analyzer", {}).get("channels", [])
    data: dict[str, Any] = {
        "id": task.case_id,
        "task": task.task_id,
        "name": task.name,
        "simulator": task.board_profile.backend,
        "board": task.board,
        "paths": case_manifest_paths(task, paths),
    }
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
    if task.board_profile.firmware_kind == "espidf_flasher_args":
        firmware = "artifacts/build/flasher_args.json"
        elf = f"artifacts/build/{task.sketch_name}.elf"
    else:
        firmware = f"artifacts/build/{task.sketch_name}.ino{paths.firmware_extension}"
        elf = f"artifacts/build/{task.sketch_name}.ino.elf"
    lines = [
        "[wokwi]",
        "version = 1",
        f"firmware = '{firmware}'",
        f"elf = '{elf}'",
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
    if paths.firmware_kind == "zephyr_image":
        return (
            paths.build_dir / "zephyr" / "zephyr.hex",
            paths.build_dir / "zephyr" / "zephyr.elf",
        )
    if paths.wokwi_toml.exists():
        configured = read_wokwi_firmware_paths(paths)
        if configured:
            return configured
    if paths.firmware_kind == "espidf_flasher_args":
        return (
            paths.build_dir / "flasher_args.json",
            paths.build_dir / f"{paths.sketch_name}.elf",
        )
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
    if task.board_profile.build_kind == "espidf":
        ensure_espidf_project_files(task, sketch_dir)
        return
    if task.board_profile.build_kind == "zephyr":
        ensure_zephyr_project_files(task, sketch_dir)
        return
    ensure_arduino_sketch_files(task, sketch_dir)


def ensure_arduino_sketch_files(task: TaskConfig, sketch_dir: Path) -> None:
    sketch_dir.mkdir(parents=True, exist_ok=True)
    sketch_yaml = sketch_dir / "sketch.yaml"
    if not sketch_yaml.exists():
        sketch_yaml.write_text(
            f"default_fqbn: {task.board_profile.fqbn}\n", encoding="utf-8"
        )
    ino_path = sketch_dir / f"{task.sketch_name}.ino"
    if not ino_path.exists() or task.level in {"level2", "level3"}:
        ino_path.write_text(example_sketch(task), encoding="utf-8")


def ensure_espidf_project_files(task: TaskConfig, project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    main_dir = project_dir / "main"
    main_dir.mkdir(parents=True, exist_ok=True)
    cmake = project_dir / "CMakeLists.txt"
    if not cmake.exists():
        cmake.write_text(espidf_root_cmake(task), encoding="utf-8")
    main_cmake = main_dir / "CMakeLists.txt"
    if not main_cmake.exists():
        main_cmake.write_text(espidf_main_cmake(), encoding="utf-8")
    sdkconfig_defaults = project_dir / "sdkconfig.defaults"
    sdkconfig_text = espidf_sdkconfig_defaults()
    if not sdkconfig_defaults.exists() or sdkconfig_defaults.read_text(encoding="utf-8") != sdkconfig_text:
        sdkconfig_defaults.write_text(sdkconfig_text, encoding="utf-8")
    main_source = main_dir / "main.c"
    if not main_source.exists() or task.level in {"level2", "level3"}:
        main_source.write_text(example_sketch(task), encoding="utf-8")


def ensure_zephyr_project_files(task: TaskConfig, project_dir: Path) -> None:
    """Zephyr app skeleton. The harness owns CMakeLists.txt and prj.conf;
    submissions provide only src/main.c (mirrors the ESP-IDF arrangement)."""

    project_dir.mkdir(parents=True, exist_ok=True)
    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    cmake = project_dir / "CMakeLists.txt"
    if not cmake.exists():
        cmake.write_text(zephyr_root_cmake(task), encoding="utf-8")
    prj_conf = project_dir / "prj.conf"
    if not prj_conf.exists():
        prj_conf.write_text(zephyr_prj_conf(), encoding="utf-8")
    main_source = src_dir / "main.c"
    if not main_source.exists() or task.level in {"level2", "level3"}:
        main_source.write_text(example_sketch(task), encoding="utf-8")


def zephyr_root_cmake(task: TaskConfig) -> str:
    return f"""\
cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{{ZEPHYR_BASE}})
project({task.sketch_name})

target_sources(app PRIVATE src/main.c)
"""


def zephyr_prj_conf() -> str:
    return """\
CONFIG_GPIO=y
"""


def espidf_root_cmake(task: TaskConfig) -> str:
    return f"""\
cmake_minimum_required(VERSION 3.16)
include($ENV{{IDF_PATH}}/tools/cmake/project.cmake)
project({task.sketch_name})
"""


def espidf_main_cmake() -> str:
    return """\
idf_component_register(SRCS "main.c" INCLUDE_DIRS ".")
"""


def espidf_sdkconfig_defaults() -> str:
    return """\
CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y
CONFIG_ESP_CONSOLE_UART_DEFAULT=n
CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y
CONFIG_ESP_CONSOLE_SECONDARY_NONE=y
"""


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
        firmware_kind=task.board_profile.firmware_kind,
        vcd=(case_dir / paths["vcd"] if paths.get("vcd") else None),
        scenario=(case_dir / paths["scenario"] if paths.get("scenario") else None),
        serial_log=(case_dir / paths["serial_log"] if paths.get("serial_log") else None),
        resc=(case_dir / paths["resc"] if paths.get("resc") else None),
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
    if task.board_profile.build_kind == "espidf":
        return normalize_espidf_submission(task, source, destination)
    if task.board_profile.build_kind == "zephyr":
        return normalize_zephyr_submission(task, source, destination)

    return normalize_arduino_submission(task, source, destination)


def normalize_arduino_submission(task: TaskConfig, source: Path, destination: Path) -> Path:
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


def normalize_espidf_submission(task: TaskConfig, source: Path, destination: Path) -> Path:
    if source.is_file():
        if source.suffix.lower() not in {".c", ".cpp"}:
            raise BuildSimulationError(
                f"submitted ESP-IDF source file must be .c or .cpp: {source}",
                classification=COMPILE_FAIL,
                failure_stage=STAGE_COMPILE,
                failure_source=SOURCE_USER_CODE,
            )
        ensure_espidf_project_files(task, destination)
        main_dir = destination / "main"
        target = main_dir / ("main.cpp" if source.suffix.lower() == ".cpp" else "main.c")
        if target.name != "main.c":
            (main_dir / "CMakeLists.txt").write_text(
                'idf_component_register(SRCS "main.cpp" INCLUDE_DIRS ".")\n',
                encoding="utf-8",
            )
            main_c = main_dir / "main.c"
            if main_c.exists():
                main_c.unlink()
        shutil.copy2(source, target)
        return destination

    cmake = source / "CMakeLists.txt"
    main_cmake = source / "main" / "CMakeLists.txt"
    source_files = sorted((source / "main").glob("*.c")) + sorted((source / "main").glob("*.cpp"))
    if not cmake.exists() or not main_cmake.exists() or not source_files:
        raise BuildSimulationError(
            f"submitted ESP-IDF project must contain CMakeLists.txt, main/CMakeLists.txt, and main/*.c or main/*.cpp: {source}",
            classification=COMPILE_FAIL,
            failure_stage=STAGE_COMPILE,
            failure_source=SOURCE_USER_CODE,
        )
    shutil.copytree(source, destination)
    return destination


def normalize_zephyr_submission(task: TaskConfig, source: Path, destination: Path) -> Path:
    """Zephyr submissions are a single C source file (the harness owns
    CMakeLists.txt and prj.conf) or a full app directory matching the
    skeleton layout."""

    if source.is_file():
        if source.suffix.lower() != ".c":
            raise BuildSimulationError(
                f"submitted Zephyr source file must be .c: {source}",
                classification=COMPILE_FAIL,
                failure_stage=STAGE_COMPILE,
                failure_source=SOURCE_USER_CODE,
            )
        ensure_zephyr_project_files(task, destination)
        shutil.copy2(source, destination / "src" / "main.c")
        return destination

    cmake = source / "CMakeLists.txt"
    prj_conf = source / "prj.conf"
    sources = sorted((source / "src").glob("*.c"))
    if not cmake.exists() or not prj_conf.exists() or not sources:
        raise BuildSimulationError(
            f"submitted Zephyr project must contain CMakeLists.txt, prj.conf, and src/*.c: {source}",
            classification=COMPILE_FAIL,
            failure_stage=STAGE_COMPILE,
            failure_source=SOURCE_USER_CODE,
        )
    shutil.copytree(source, destination)
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
    idf_py: str = "idf.py",
    wokwi_cli: str = "wokwi-cli",
    west: str = "west",
    renode_cli: str = "renode",
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
                idf_py=idf_py,
                wokwi_cli=wokwi_cli,
                west=west,
                renode_cli=renode_cli,
                enforce_tool_versions=enforce_tool_versions,
            )
        return

    build_case(task, paths, arduino_cli=arduino_cli, idf_py=idf_py, west=west)
    if task.simulation_variants:
        simulate_variants(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
            renode_cli=renode_cli,
        )
    else:
        simulate_case(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
            renode_cli=renode_cli,
        )
    ensure_existing_variant_outputs(task, paths)


def build_case(
    task: TaskConfig,
    paths: CasePaths,
    *,
    arduino_cli: str = "arduino-cli",
    idf_py: str = "idf.py",
    west: str = "west",
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
            f"platform description not found: {paths.diagram}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
        )
    if task.board_profile.backend != "renode" and not paths.wokwi_toml.exists():
        raise BuildSimulationError(
            f"wokwi.toml not found: {paths.wokwi_toml}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
        )

    clean_build_dir(paths)

    if task.board_profile.build_kind == "espidf":
        build_espidf_case(task, paths, idf_py=idf_py)
    elif task.board_profile.build_kind == "zephyr":
        build_zephyr_case(task, paths, west=west)
    else:
        build_arduino_case(paths, arduino_cli=arduino_cli)
    ensure_firmware_outputs(paths)


def build_arduino_case(paths: CasePaths, *, arduino_cli: str) -> None:
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


def build_espidf_case(task: TaskConfig, paths: CasePaths, *, idf_py: str) -> None:
    target = task.board_profile.idf_target
    sketch_arg = relative_to(paths.sketch, paths.case_dir)
    build_arg = relative_to(paths.build_dir, paths.case_dir)
    idf_args = [
        "-C",
        sketch_arg,
        "-B",
        build_arg,
    ]
    if target:
        idf_args.append(f"-DIDF_TARGET={target}")
    idf_args.append("build")
    command = command_with_windows_batch_wrapper(idf_py, idf_args)
    run_checked(
        command,
        cwd=paths.case_dir,
        stage="compile",
        timeout_s=300.0,
        command_failure_classification=COMPILE_FAIL,
        command_failure_stage=STAGE_COMPILE,
        infra_failure_classification=SIM_INFRA_FAIL,
        infra_failure_stage=STAGE_SIM_INFRA,
        command_failure_source=SOURCE_USER_CODE,
        infra_failure_source=SOURCE_ENVIRONMENT,
    )


def build_zephyr_case(task: TaskConfig, paths: CasePaths, *, west: str = "west") -> None:
    """west build, staged to a space-free directory.

    Zephyr's kconfig.cmake fails on application paths containing spaces
    (verified live; this repo's path contains "! IoT"), so the app sources
    are copied to a staging dir, built there, and zephyr.elf/zephyr.hex are
    copied back into the case's artifacts/build/zephyr/.

    Failure mapping: the harness owns CMakeLists.txt and prj.conf, so a
    CMake configure failure cannot be caused by the submitted main.c and is
    an environment problem (-> IF). Only the compile step is charged as CF.
    """

    west_exe = renode.west_executable(west)
    workspace = renode.zephyr_workspace()
    if not workspace.exists():
        raise BuildSimulationError(
            f"Zephyr workspace not found: {workspace} (set ZEPHYR_WORKSPACE)",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_ENVIRONMENT,
        )
    board = task.board_profile.zephyr_board
    if not board:
        raise BuildSimulationError(
            f"{task.task_id}: board profile has no zephyr_board",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
        )

    stage_root = renode.zephyr_build_root()
    if " " in str(stage_root):
        raise BuildSimulationError(
            f"Zephyr staging dir contains spaces: {stage_root} (set IOTBENCH_ZEPHYR_BUILD_ROOT)",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_ENVIRONMENT,
        )
    stage = stage_root / safe_filename_part(paths.case_id)
    app_dir = stage / "app"
    build_dir = stage / "build"
    if stage.exists():
        shutil.rmtree(stage)
    app_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(paths.sketch, app_dir)

    env = renode.zephyr_build_env()
    base_cmd = [
        west_exe,
        "build",
        "-b",
        board,
        str(app_dir),
        "--build-dir",
        str(build_dir),
    ]
    # Configure first: failures here are environment problems (-> IF).
    run_checked(
        [*base_cmd[:2], "-p", "always", *base_cmd[2:], "--cmake-only"],
        cwd=workspace,
        stage="zephyr configure",
        timeout_s=600.0,
        env=env,
        command_failure_classification=SIM_INFRA_FAIL,
        command_failure_stage=STAGE_SIM_INFRA,
        infra_failure_classification=SIM_INFRA_FAIL,
        infra_failure_stage=STAGE_SIM_INFRA,
        command_failure_source=SOURCE_ENVIRONMENT,
        infra_failure_source=SOURCE_ENVIRONMENT,
    )
    # Compile: failures here are attributable to the submitted source (-> CF).
    run_checked(
        base_cmd,
        cwd=workspace,
        stage="zephyr compile",
        timeout_s=600.0,
        env=env,
        command_failure_classification=COMPILE_FAIL,
        command_failure_stage=STAGE_COMPILE,
        infra_failure_classification=SIM_INFRA_FAIL,
        infra_failure_stage=STAGE_SIM_INFRA,
        command_failure_source=SOURCE_USER_CODE,
        infra_failure_source=SOURCE_ENVIRONMENT,
    )

    produced_dir = build_dir / "zephyr"
    destination_dir = paths.build_dir / "zephyr"
    destination_dir.mkdir(parents=True, exist_ok=True)
    for name in ("zephyr.elf", "zephyr.hex"):
        produced = produced_dir / name
        if produced.exists():
            shutil.copy2(produced, destination_dir / name)


def command_with_windows_batch_wrapper(command: str, args: list[str]) -> list[str]:
    if sys.platform == "win32" and Path(command).suffix.lower() in {".cmd", ".bat"}:
        powershell_command = " ".join([powershell_quote(command), *(powershell_quote(arg) for arg in args)])
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"& {powershell_command}"]
    return [command, *args]


def powershell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def simulate_case(
    task: TaskConfig,
    paths: CasePaths,
    *,
    simulation_time_ms: int | None = None,
    wokwi_cli: str = "wokwi-cli",
    renode_cli: str = "renode",
) -> None:
    if task.board_profile.backend == "renode":
        simulate_case_renode(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            renode_cli=renode_cli,
        )
        return
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


def simulate_case_renode(
    task: TaskConfig,
    paths: CasePaths,
    *,
    simulation_time_ms: int | None = None,
    renode_cli: str = "renode",
) -> None:
    ensure_artifact_dirs(paths)
    ensure_firmware_outputs(paths)
    if not paths.diagram.exists():
        raise BuildSimulationError(
            f"platform description not found: {paths.diagram}",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
        )
    if paths.resc is None:
        raise BuildSimulationError(
            f"{task.task_id}: Renode case has no resc path",
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
        )

    archive_current_outputs(paths)
    if paths.vcd:
        paths.vcd.parent.mkdir(parents=True, exist_ok=True)
    if paths.serial_log:
        paths.serial_log.parent.mkdir(parents=True, exist_ok=True)

    timeout_ms = simulation_time_ms or int(task.simulation.get("timeout_ms", 5000))
    # The resc is a deterministic function of (task, paths, timeout); re-emit
    # so a simulation-time override or scenario change is always honored.
    try:
        write_case_resc(task, paths, generate_scenario(task), timeout_ms=timeout_ms)
    except renode.RenodeConfigError as exc:
        raise BuildSimulationError(
            str(exc),
            classification=SIM_INFRA_FAIL,
            failure_stage=STAGE_SIM_INFRA,
            failure_source=SOURCE_HARNESS,
        ) from exc

    renode_exe = renode.renode_executable(renode_cli)
    resc_rel = relative_to(paths.resc, paths.case_dir)
    run_checked(
        [
            renode_exe,
            "--disable-xwt",
            "--console",
            "-e",
            f"include @{resc_rel}",
        ],
        cwd=paths.case_dir,
        stage="renode simulation",
        # Renode runs at roughly 3x wall/virtual on this hardware plus ~5s
        # startup; the guard is generous so a hang is an IF, not a flake.
        timeout_s=max(60.0, timeout_ms / 1000.0 * 10.0 + 30.0),
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
    idf_py: str = "idf.py",
    wokwi_cli: str = "wokwi-cli",
    west: str = "west",
    renode_cli: str = "renode",
    command: str = "run",
) -> dict[str, Any]:
    build_case(task, paths, arduino_cli=arduino_cli, idf_py=idf_py, west=west)
    if task.simulation_variants:
        simulate_variants(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
            renode_cli=renode_cli,
        )
    else:
        simulate_case(
            task,
            paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
            renode_cli=renode_cli,
        )
    result = validate_case(task, paths)
    write_verification(
        task,
        paths,
        result,
        command=command,
        arduino_cli=arduino_cli,
        idf_py=idf_py,
        wokwi_cli=wokwi_cli,
        west=west,
        renode_cli=renode_cli,
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
    renode_cli: str = "renode",
) -> list[CasePaths]:
    simulated: list[CasePaths] = []
    is_renode = task.board_profile.backend == "renode"
    for variant in task.simulation_variants:
        variant_paths = paths_for_variant(paths, variant_id(variant), variant)
        if is_renode:
            if variant.get("attrs"):
                raise CaseConfigError(
                    f"{task.task_id}: per-variant attrs are not supported by the "
                    "Renode backend yet; use per-variant scenario overrides"
                )
            variant_paths.diagram.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths.diagram, variant_paths.diagram)
        else:
            write_variant_diagram(paths.diagram, variant_paths.diagram, variant)
        proxy = task_for_variant(task, variant)
        if variant_scenario_override(variant) is not None and variant_paths.scenario:
            write_scenario(variant_paths.scenario, generate_scenario(proxy))
        simulate_case(
            proxy,
            variant_paths,
            simulation_time_ms=simulation_time_ms,
            wokwi_cli=wokwi_cli,
            renode_cli=renode_cli,
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
    is_renode = paths.resc is not None
    return replace(
        paths,
        resc=(variant_dir / "case.resc" if is_renode else None),
        diagram=variant_dir / ("case.repl" if is_renode else "diagram.json"),
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
    if paths.firmware_kind == "espidf_flasher_args":
        candidate_names = ["flasher_args.json", f"{paths.sketch_name}.elf"]
    else:
        candidate_names = [
            f"{paths.sketch_name}.ino{paths.firmware_extension}",
            f"{paths.sketch_name}.ino.elf",
        ]
    candidates = []
    for name in candidate_names:
        candidates.append(paths.build_dir / name)
        candidates.extend(paths.build_dir.rglob(name))
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
    env: dict[str, str] | None = None,
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
            env=env,
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
    idf_py: str = "idf.py",
    wokwi_cli: str = "wokwi-cli",
    west: str = "west",
    renode_cli: str = "renode",
) -> Path:
    tool_versions = current_tool_versions(
        arduino_cli=arduino_cli,
        idf_py=idf_py,
        wokwi_cli=wokwi_cli,
        west=west,
        renode_cli=renode_cli,
        build_kind=task.board_profile.build_kind,
    )
    manifest = {
        "manifest_version": 2,
        "task_id": task.task_id,
        "case_id": paths.case_id,
        "command": command,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "arduino_cli_version": tool_versions["arduino_cli_version"],
        "idf_py_version": tool_versions["idf_py_version"],
        "wokwi_cli_version": tool_versions["wokwi_cli_version"],
        "renode_version": tool_versions["renode_version"],
        "west_version": tool_versions["west_version"],
        "zephyr_revision": tool_versions["zephyr_revision"],
        "sketch_path": relative_to(paths.sketch, paths.case_dir),
        "sketch_hash": hash_path(paths.sketch),
        "diagram_path": relative_to(paths.diagram, paths.case_dir),
        "diagram_hash": hash_file(paths.diagram),
        "scenario_path": relative_to(paths.scenario, paths.case_dir) if paths.scenario else None,
        "scenario_hash": hash_file(paths.scenario) if paths.scenario else None,
        "resc_path": relative_to(paths.resc, paths.case_dir) if paths.resc else None,
        "resc_hash": hash_file(paths.resc) if paths.resc else None,
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
                    "resc_path": (
                        relative_to(variant_paths.resc, paths.case_dir) if variant_paths.resc else None
                    ),
                    "resc_hash": hash_file(variant_paths.resc) if variant_paths.resc else None,
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
    idf_py: str = "idf.py",
    wokwi_cli: str = "wokwi-cli",
    west: str = "west",
    renode_cli: str = "renode",
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
        validate_manifest_tool_versions(
            manifest,
            arduino_cli=arduino_cli,
            idf_py=idf_py,
            wokwi_cli=wokwi_cli,
            west=west,
            renode_cli=renode_cli,
            build_kind=task.board_profile.build_kind,
        )

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
    if paths.resc and not task.simulation_variants:
        checks.append(("resc", manifest.get("resc_hash"), hash_file(paths.resc)))
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
            if variant_paths.resc:
                checks.append(
                    (f"variant {sanitized} resc", entry.get("resc_hash"), hash_file(variant_paths.resc))
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
        "idf_py_version": data.get("idf_py_version"),
        "wokwi_cli_version": data.get("wokwi_cli_version"),
        "renode_version": data.get("renode_version"),
        "west_version": data.get("west_version"),
        "zephyr_revision": data.get("zephyr_revision"),
    }


def current_tool_versions(
    *,
    arduino_cli: str = "arduino-cli",
    idf_py: str = "idf.py",
    wokwi_cli: str = "wokwi-cli",
    west: str = "west",
    renode_cli: str = "renode",
    build_kind: str | None = None,
) -> dict[str, str | None]:
    """Probe tool versions. Only the tools relevant to ``build_kind`` are
    probed (renode startup alone costs seconds); pass ``build_kind=None`` to
    probe everything (doctor)."""

    probe_wokwi = build_kind in (None, "arduino", "espidf")
    probe_zephyr = build_kind in (None, "zephyr")
    return {
        "arduino_cli_version": (
            command_version(arduino_cli, "version") if build_kind in (None, "arduino") else None
        ),
        "idf_py_version": (
            command_version(idf_py, "--version") if build_kind in (None, "espidf") else None
        ),
        "wokwi_cli_version": (
            command_version(wokwi_cli, "--version") if probe_wokwi else None
        ),
        "renode_version": (
            command_version(renode.renode_executable(renode_cli), "--version")
            if probe_zephyr
            else None
        ),
        "west_version": (
            command_version(renode.west_executable(west), "--version") if probe_zephyr else None
        ),
        "zephyr_revision": renode.zephyr_revision() if probe_zephyr else None,
    }


def tool_version_report(
    *,
    arduino_cli: str = "arduino-cli",
    idf_py: str = "idf.py",
    wokwi_cli: str = "wokwi-cli",
    west: str = "west",
    renode_cli: str = "renode",
    build_kind: str = "arduino",
) -> dict[str, Any]:
    expected = pinned_tool_versions()
    actual = current_tool_versions(
        arduino_cli=arduino_cli,
        idf_py=idf_py,
        wokwi_cli=wokwi_cli,
        west=west,
        renode_cli=renode_cli,
        build_kind=build_kind,
    )
    mismatches = []
    for key, label in tool_version_keys_for_build(build_kind):
        if expected.get(key) is not None and expected.get(key) != actual.get(key):
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
    idf_py: str = "idf.py",
    wokwi_cli: str = "wokwi-cli",
    west: str = "west",
    renode_cli: str = "renode",
    build_kind: str = "arduino",
) -> dict[str, Any]:
    report = tool_version_report(
        arduino_cli=arduino_cli,
        idf_py=idf_py,
        wokwi_cli=wokwi_cli,
        west=west,
        renode_cli=renode_cli,
        build_kind=build_kind,
    )
    if not report["ok"]:
        raise tool_version_mismatch_error(report)
    return report


def validate_manifest_tool_versions(
    manifest: dict[str, Any],
    *,
    arduino_cli: str,
    idf_py: str,
    wokwi_cli: str,
    west: str = "west",
    renode_cli: str = "renode",
    build_kind: str = "arduino",
) -> None:
    current = current_tool_versions(
        arduino_cli=arduino_cli,
        idf_py=idf_py,
        wokwi_cli=wokwi_cli,
        west=west,
        renode_cli=renode_cli,
        build_kind=build_kind,
    )
    for key, label in tool_version_keys_for_build(build_kind):
        recorded = manifest.get(key)
        if recorded is None and key == "idf_py_version" and build_kind != "espidf":
            continue
        actual = current.get(key)
        if recorded != actual:
            raise artifact_provenance_error(
                f"{label} version does not match the verification manifest "
                f"(recorded {recorded!r}, current {actual!r}); rerun the full pipeline"
            )


def tool_version_keys_for_build(build_kind: str) -> tuple[tuple[str, str], ...]:
    if build_kind == "espidf":
        return (
            ("idf_py_version", "idf.py"),
            ("wokwi_cli_version", "wokwi-cli"),
        )
    if build_kind == "zephyr":
        return (
            ("renode_version", "renode"),
            ("west_version", "west"),
            ("zephyr_revision", "zephyr"),
        )
    return (
        ("arduino_cli_version", "arduino-cli"),
        ("wokwi_cli_version", "wokwi-cli"),
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
    if task.board_profile.build_kind == "espidf":
        return espidf_example_source(task)
    if task.board_profile.build_kind == "zephyr":
        return zephyr_example_source(task)
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


def zephyr_gpio_parts(pin_spec: str) -> tuple[str, int]:
    port, index = renode.parse_gpio_pin(pin_spec)
    return port, index


def zephyr_example_source(task: TaskConfig) -> str:
    examples = {
        "blink_led_1hz": zephyr_blink_1hz,
    }
    factory = examples.get(task.task_id)
    return factory(task) if factory else "int main(void) { return 0; }\n"


def zephyr_blink_1hz(task: TaskConfig) -> str:
    pin = fixture_pin(task, "led")
    port, index = zephyr_gpio_parts(pin)
    return f"""\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const led_port = DEVICE_DT_GET(DT_NODELABEL({port}));

int main(void)
{{
\tgpio_pin_configure(led_port, {index}, GPIO_OUTPUT_LOW);
\twhile (1) {{
\t\tgpio_pin_toggle(led_port, {index});
\t\tk_msleep(500);
\t}}
\treturn 0;
}}
"""


def espidf_example_source(task: TaskConfig) -> str:
    examples = {
        "blink_led_1hz": espidf_blink_1hz,
        "blink_led_morse_code": espidf_morse_sos,
        "blink_led_no_delay": espidf_blink_no_delay,
        "blink_two_leds": espidf_blink_two_leds,
        "buzzer_doorbell": espidf_buzzer_doorbell,
        "buzzer_button": espidf_buzzer_button,
        "button_status_display": espidf_button_status_display,
        "button_status_count": espidf_button_status_count,
        "button_press_debounce": espidf_button_press_debounce,
        "breathing_led": espidf_breathing_led,
        "sensor_pir_human_motion": espidf_pir_serial,
        "tmp36_read": espidf_tmp36_read,
        "rotary_encoder": espidf_rotary_encoder,
        "16key_keypad": espidf_keypad_scan,
        "lcd1602_display_hello_world": espidf_lcd_hello,
        "dht11_read": espidf_dht11_read,
        "ds1307_rtc": espidf_i2c_serial_stub,
        "mpu6050_read_i2c": espidf_mpu6050_i2c_serial,
        "mpu6050_read_spi": espidf_spi_serial_stub,
        "bme280_read_i2c": espidf_bme280_i2c_stub,
        "bme280_read_spi": espidf_bme280_spi_stub,
        "tilt_detection_alarm": espidf_digital_follow,
        "photoresistor_nightlight": espidf_adc_threshold_led,
        "ds18b20_heat_alarm": espidf_ds18b20_heat_alarm,
        "clap_switch": espidf_clap_switch,
        "hcsr501_motion_alarm": espidf_digital_follow,
        "hcsr04_find_distance": espidf_hcsr04_serial,
        "parking_sensor": espidf_parking_sensor,
        "reverse_parking_sensor": espidf_reverse_parking_sensor,
        "dht11_read_button_display": espidf_lcd_dht,
        "mpu6050_read_button_display": espidf_lcd_mpu,
        "mpu6050_read_periodic_display": espidf_lcd_mpu,
        "safebox": espidf_safebox,
        "safebox_display": espidf_safebox_display,
        "lcd1602_auto_brightness_control": espidf_lcd_brightness,
        "buzzer_toggle_led_freq": espidf_buzzer_toggle_led_freq,
        "tmp36_read_button_display": espidf_tmp36_button_lcd,
        "tmp36_read_periodic_display": espidf_tmp36_periodic_lcd,
        "reaction_timer_display": espidf_reaction_timer_lcd,
        "sensor_water_level_display": espidf_water_level_lcd,
        "buzzer_laser_tripwire": espidf_laser_tripwire,
        "joystick_buzzer_pitch": espidf_joystick_pitch,
        "step_counter_print": espidf_step_counter,
    }
    factory = examples.get(task.task_id)
    return factory(task) if factory else "void app_main(void) {}\n"


def espidf_common_includes(
    *,
    adc: bool = False,
    ledc: bool = False,
    i2c: bool = False,
    spi: bool = False,
    rom: bool = False,
    string: bool = False,
) -> str:
    includes = [
        "#include <stdio.h>",
        "#include <stdint.h>",
        "#include \"driver/gpio.h\"",
        "#include \"esp_timer.h\"",
        "#include \"freertos/FreeRTOS.h\"",
        "#include \"freertos/task.h\"",
    ]
    if string:
        includes.append("#include <string.h>")
    if ledc:
        includes.append("#include \"driver/ledc.h\"")
    if adc:
        includes.append("#include \"esp_adc/adc_oneshot.h\"")
    if i2c:
        includes.append("#include \"driver/i2c.h\"")
    if spi:
        includes.append("#include \"driver/spi_master.h\"")
    if rom:
        includes.append("#include \"esp_rom_sys.h\"")
    return "\n".join(includes) + "\n\n"


def espidf_gpio_output_setup(pin_name: str) -> str:
    return f"  gpio_reset_pin({pin_name});\n  gpio_set_direction({pin_name}, GPIO_MODE_OUTPUT);\n"


def espidf_gpio_input_setup(pin_name: str) -> str:
    return f"  gpio_reset_pin({pin_name});\n  gpio_set_direction({pin_name}, GPIO_MODE_INPUT);\n"


def espidf_blink_1hz(task: TaskConfig) -> str:
    pin = fixture_pin(task, "led")
    return espidf_common_includes() + f"""\
#define LED_PIN GPIO_NUM_{pin}

void app_main(void) {{
{espidf_gpio_output_setup("LED_PIN")}  int level = 0;
  while (1) {{
    level = !level;
    gpio_set_level(LED_PIN, level);
    vTaskDelay(pdMS_TO_TICKS(500));
  }}
}}
"""


def espidf_morse_sos(task: TaskConfig) -> str:
    pin = fixture_pin(task, "led")
    return espidf_common_includes() + f"""\
#define LED_PIN GPIO_NUM_{pin}

static void set_led_for_units(int level, int units) {{
  gpio_set_level(LED_PIN, level);
  vTaskDelay(pdMS_TO_TICKS(200 * units));
}}

void app_main(void) {{
{espidf_gpio_output_setup("LED_PIN")}  const int pattern[] = {{1, 1, 1, 3, 3, 3, 1, 1, 1}};
  while (1) {{
    for (int i = 0; i < 9; ++i) {{
      set_led_for_units(1, pattern[i]);
      if (i < 8) {{
        set_led_for_units(0, (i == 2 || i == 5) ? 3 : 1);
      }}
    }}
    set_led_for_units(0, 7);
  }}
}}
"""


def espidf_blink_no_delay(task: TaskConfig) -> str:
    pin = fixture_pin(task, "led")
    return espidf_common_includes() + f"""\
#define LED_PIN GPIO_NUM_{pin}

void app_main(void) {{
{espidf_gpio_output_setup("LED_PIN")}  int level = 0;
  int64_t last_toggle_us = esp_timer_get_time();
  while (1) {{
    int64_t now = esp_timer_get_time();
    if (now - last_toggle_us >= 500000) {{
      last_toggle_us += 500000;
      level = !level;
      gpio_set_level(LED_PIN, level);
    }}
    taskYIELD();
  }}
}}
"""


def espidf_blink_two_leds(task: TaskConfig) -> str:
    pins = task.fixture.get("pins", {}) if isinstance(task.fixture, dict) else {}
    led1 = str(pins.get("led1", task.board_profile.default_pins["led"]))
    led2 = str(pins.get("led2", task.board_profile.default_pins["led2"]))
    return espidf_common_includes() + f"""\
#define LED1_PIN GPIO_NUM_{led1}
#define LED2_PIN GPIO_NUM_{led2}

void app_main(void) {{
{espidf_gpio_output_setup("LED1_PIN")}{espidf_gpio_output_setup("LED2_PIN")}  int led1 = 0;
  int led2 = 0;
  int64_t last_led1_us = esp_timer_get_time();
  int64_t last_led2_us = last_led1_us;
  while (1) {{
    int64_t now = esp_timer_get_time();
    if (now - last_led1_us >= 500000) {{
      last_led1_us += 500000;
      led1 = !led1;
      gpio_set_level(LED1_PIN, led1);
    }}
    if (now - last_led2_us >= 250000) {{
      last_led2_us += 250000;
      led2 = !led2;
      gpio_set_level(LED2_PIN, led2);
    }}
    taskYIELD();
  }}
}}
"""


def espidf_buzzer_doorbell(task: TaskConfig) -> str:
    button = fixture_pin(task, "button")
    buzzer = fixture_pin(task, "buzzer")
    return espidf_common_includes() + f"""\
#define BUTTON_PIN GPIO_NUM_{button}
#define BUZZER_PIN GPIO_NUM_{buzzer}

void app_main(void) {{
{espidf_gpio_input_setup("BUTTON_PIN")}{espidf_gpio_output_setup("BUZZER_PIN")}  while (1) {{
    gpio_set_level(BUZZER_PIN, gpio_get_level(BUTTON_PIN));
    vTaskDelay(pdMS_TO_TICKS(1));
  }}
}}
"""


def espidf_buzzer_button(task: TaskConfig) -> str:
    button = fixture_pin(task, "button")
    buzzer = fixture_pin(task, "buzzer")
    return espidf_common_includes() + f"""\
#define BUTTON_PIN GPIO_NUM_{button}
#define BUZZER_PIN GPIO_NUM_{buzzer}
#define DEBOUNCE_US 30000

void app_main(void) {{
{espidf_gpio_input_setup("BUTTON_PIN")}{espidf_gpio_output_setup("BUZZER_PIN")}  int stable = 0;
  int last_reading = 0;
  int64_t changed_at = esp_timer_get_time();
  while (1) {{
    int reading = gpio_get_level(BUTTON_PIN);
    int64_t now = esp_timer_get_time();
    if (reading != last_reading) {{
      last_reading = reading;
      changed_at = now;
    }}
    if (now - changed_at >= DEBOUNCE_US && stable != reading) {{
      stable = reading;
    }}
    gpio_set_level(BUZZER_PIN, stable);
    vTaskDelay(pdMS_TO_TICKS(1));
  }}
}}
"""


def espidf_button_status_display(task: TaskConfig) -> str:
    button = fixture_pin(task, "button")
    return espidf_common_includes() + f"""\
#define BUTTON_PIN GPIO_NUM_{button}

void app_main(void) {{
{espidf_gpio_input_setup("BUTTON_PIN")}  int was_pressed = 0;
  while (1) {{
    int pressed = gpio_get_level(BUTTON_PIN);
    if (pressed && !was_pressed) {{
      printf("Button Pressed!\\n");
    }}
    was_pressed = pressed;
    vTaskDelay(pdMS_TO_TICKS(5));
  }}
}}
"""


def espidf_button_status_count(task: TaskConfig) -> str:
    button = fixture_pin(task, "button")
    return espidf_common_includes() + f"""\
#define BUTTON_PIN GPIO_NUM_{button}

void app_main(void) {{
{espidf_gpio_input_setup("BUTTON_PIN")}  int was_pressed = 0;
  int count = 0;
  while (1) {{
    int pressed = gpio_get_level(BUTTON_PIN);
    if (pressed && !was_pressed) {{
      ++count;
      printf("%d\\n", count);
    }}
    was_pressed = pressed;
    vTaskDelay(pdMS_TO_TICKS(5));
  }}
}}
"""


def espidf_button_press_debounce(task: TaskConfig) -> str:
    button = fixture_pin(task, "button")
    return espidf_common_includes() + f"""\
#define BUTTON_PIN GPIO_NUM_{button}
#define DEBOUNCE_US 30000

void app_main(void) {{
{espidf_gpio_input_setup("BUTTON_PIN")}  int stable = 0;
  int last_reading = 0;
  int64_t changed_at = esp_timer_get_time();
  while (1) {{
    int reading = gpio_get_level(BUTTON_PIN);
    int64_t now = esp_timer_get_time();
    if (reading != last_reading) {{
      last_reading = reading;
      changed_at = now;
    }}
    if (now - changed_at >= DEBOUNCE_US && stable != reading) {{
      stable = reading;
      if (stable) {{
        printf("Button Pressed!\\n");
      }}
    }}
    vTaskDelay(pdMS_TO_TICKS(1));
  }}
}}
"""


def espidf_breathing_led(task: TaskConfig) -> str:
    pin = fixture_pin(task, "led")
    return espidf_common_includes(ledc=True) + f"""\
#define LED_PIN GPIO_NUM_{pin}
#define LEDC_DUTY_MAX 1023

void app_main(void) {{
  ledc_timer_config_t timer = {{
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .timer_num = LEDC_TIMER_0,
    .duty_resolution = LEDC_TIMER_10_BIT,
    .freq_hz = 1000,
    .clk_cfg = LEDC_AUTO_CLK,
  }};
  ledc_timer_config(&timer);
  ledc_channel_config_t channel = {{
    .gpio_num = LED_PIN,
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .channel = LEDC_CHANNEL_0,
    .intr_type = LEDC_INTR_DISABLE,
    .timer_sel = LEDC_TIMER_0,
    .duty = 0,
    .hpoint = 0,
  }};
  ledc_channel_config(&channel);

  while (1) {{
    for (int level = 1; level <= 50; ++level) {{
      ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, level * LEDC_DUTY_MAX / 50);
      ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
      vTaskDelay(pdMS_TO_TICKS(10));
    }}
    for (int level = 50; level >= 1; --level) {{
      ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, level * LEDC_DUTY_MAX / 50);
      ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
      vTaskDelay(pdMS_TO_TICKS(10));
    }}
  }}
}}
"""


def espidf_pir_serial(task: TaskConfig) -> str:
    pir = fixture_pin(task, "pir")
    return espidf_common_includes() + f"""\
#define PIR_PIN GPIO_NUM_{pir}

void app_main(void) {{
{espidf_gpio_input_setup("PIR_PIN")}  int last_state = -1;
  while (1) {{
    int state = gpio_get_level(PIR_PIN);
    if (state != last_state) {{
      printf("%s\\n", state ? "Motion Detected!" : "No Motion Detected!");
      last_state = state;
    }}
    vTaskDelay(pdMS_TO_TICKS(10));
  }}
}}
"""


def espidf_tmp36_read(task: TaskConfig) -> str:
    profile = task.board_profile
    return espidf_common_includes(adc=True) + f"""\
#define TMP36_CHANNEL ADC_CHANNEL_8

void app_main(void) {{
  adc_oneshot_unit_handle_t adc_handle;
  adc_oneshot_unit_init_cfg_t init_config = {{
    .unit_id = ADC_UNIT_1,
  }};
  adc_oneshot_new_unit(&init_config, &adc_handle);
  adc_oneshot_chan_cfg_t channel_config = {{
    .atten = ADC_ATTEN_DB_12,
    .bitwidth = ADC_BITWIDTH_12,
  }};
  adc_oneshot_config_channel(adc_handle, TMP36_CHANNEL, &channel_config);

  while (1) {{
    int raw = 0;
    adc_oneshot_read(adc_handle, TMP36_CHANNEL, &raw);
    float voltage = raw * ({profile.voltage:.6g}f / {float(profile.adc_max):.1f}f);
    float celsius = (voltage - 0.5f) * 100.0f;
    printf("%.1f\\n", celsius);
    vTaskDelay(pdMS_TO_TICKS(100));
  }}
}}
"""


def espidf_lcd_driver_source() -> str:
    return """\
#define LCD_RS GPIO_NUM_38
#define LCD_E GPIO_NUM_39
#define LCD_D4 GPIO_NUM_40
#define LCD_D5 GPIO_NUM_41
#define LCD_D6 GPIO_NUM_42
#define LCD_D7 GPIO_NUM_21

static void lcd_gpio_init(void) {
  const gpio_num_t pins[] = {LCD_RS, LCD_E, LCD_D4, LCD_D5, LCD_D6, LCD_D7};
  for (int i = 0; i < 6; ++i) {
    gpio_reset_pin(pins[i]);
    gpio_set_direction(pins[i], GPIO_MODE_OUTPUT);
  }
}

static void lcd_pulse(void) {
  gpio_set_level(LCD_E, 1);
  esp_rom_delay_us(1);
  gpio_set_level(LCD_E, 0);
  esp_rom_delay_us(60);
}

static void lcd_nibble(uint8_t value) {
  gpio_set_level(LCD_D4, value & 1);
  gpio_set_level(LCD_D5, (value >> 1) & 1);
  gpio_set_level(LCD_D6, (value >> 2) & 1);
  gpio_set_level(LCD_D7, (value >> 3) & 1);
  lcd_pulse();
}

static void lcd_write(uint8_t value, int rs) {
  gpio_set_level(LCD_RS, rs);
  lcd_nibble(value >> 4);
  lcd_nibble(value & 0x0f);
}

static void lcd_command(uint8_t value) {
  lcd_write(value, 0);
  if (value == 1) {
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

static void lcd_data(uint8_t value) {
  lcd_write(value, 1);
}

static void lcd_begin(void) {
  lcd_gpio_init();
  vTaskDelay(pdMS_TO_TICKS(50));
  lcd_command(0x28);
  lcd_command(0x0c);
  lcd_command(0x06);
  lcd_command(0x01);
}

static void lcd_clear(void) { lcd_command(0x01); }
static void lcd_set_cursor(int col, int row) { lcd_command((row ? 0xc0 : 0x80) + col); }
static void lcd_print(const char *text) {
  while (*text) {
    lcd_data((uint8_t)*text++);
  }
}
"""


def espidf_adc_gpio9_source() -> str:
    return """\
static adc_oneshot_unit_handle_t adc_handle;

static void adc_gpio9_init(void) {
  adc_oneshot_unit_init_cfg_t init_config = {.unit_id = ADC_UNIT_1};
  adc_oneshot_new_unit(&init_config, &adc_handle);
  adc_oneshot_chan_cfg_t channel_config = {
    .atten = ADC_ATTEN_DB_12,
    .bitwidth = ADC_BITWIDTH_12,
  };
  adc_oneshot_config_channel(adc_handle, ADC_CHANNEL_8, &channel_config);
}

static int adc_gpio9_read(void) {
  int raw = 0;
  adc_oneshot_read(adc_handle, ADC_CHANNEL_8, &raw);
  return raw;
}
"""


def espidf_ledc_tone_source() -> str:
    return """\
static void ledc_tone_init(gpio_num_t pin) {
  ledc_timer_config_t timer = {
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .timer_num = LEDC_TIMER_1,
    .duty_resolution = LEDC_TIMER_10_BIT,
    .freq_hz = 1000,
    .clk_cfg = LEDC_AUTO_CLK,
  };
  ledc_timer_config(&timer);
  ledc_channel_config_t channel = {
    .gpio_num = pin,
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .channel = LEDC_CHANNEL_1,
    .intr_type = LEDC_INTR_DISABLE,
    .timer_sel = LEDC_TIMER_1,
    .duty = 0,
    .hpoint = 0,
  };
  ledc_channel_config(&channel);
}

static void ledc_tone(int freq_hz) {
  if (freq_hz <= 0) {
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 0);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
    return;
  }
  ledc_set_freq(LEDC_LOW_SPEED_MODE, LEDC_TIMER_1, freq_hz);
  ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 512);
  ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
}
"""


def espidf_i2c_setup_source(sda: str = "38", scl: str = "39") -> str:
    return f"""\
#define I2C_PORT I2C_NUM_0

static void i2c_setup(void) {{
  i2c_config_t conf = {{
    .mode = I2C_MODE_MASTER,
    .sda_io_num = GPIO_NUM_{sda},
    .scl_io_num = GPIO_NUM_{scl},
    .sda_pullup_en = GPIO_PULLUP_ENABLE,
    .scl_pullup_en = GPIO_PULLUP_ENABLE,
    .master.clk_speed = 100000,
  }};
  i2c_param_config(I2C_PORT, &conf);
  i2c_driver_install(I2C_PORT, conf.mode, 0, 0, 0);
}}

static uint8_t i2c_read_reg(uint8_t addr, uint8_t reg) {{
  uint8_t value = 0;
  i2c_master_write_read_device(I2C_PORT, addr, &reg, 1, &value, 1, pdMS_TO_TICKS(50));
  return value;
}}

static void i2c_write_reg(uint8_t addr, uint8_t reg, uint8_t value) {{
  uint8_t data[2] = {{reg, value}};
  i2c_master_write_to_device(I2C_PORT, addr, data, sizeof(data), pdMS_TO_TICKS(50));
}}
"""


def espidf_spi_activity_source(sck: str, miso: str, mosi: str, cs: str) -> str:
    return f"""\
static spi_device_handle_t spi_dev;

static void spi_setup(void) {{
  spi_bus_config_t buscfg = {{
    .miso_io_num = GPIO_NUM_{miso},
    .mosi_io_num = GPIO_NUM_{mosi},
    .sclk_io_num = GPIO_NUM_{sck},
    .quadwp_io_num = -1,
    .quadhd_io_num = -1,
  }};
  spi_device_interface_config_t devcfg = {{
    .clock_speed_hz = 1000000,
    .mode = 0,
    .spics_io_num = GPIO_NUM_{cs},
    .queue_size = 1,
  }};
  spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_DISABLED);
  spi_bus_add_device(SPI2_HOST, &devcfg, &spi_dev);
}}

static uint8_t spi_transfer(uint8_t byte) {{
  uint8_t rx = 0;
  spi_transaction_t t = {{
    .length = 8,
    .tx_buffer = &byte,
    .rx_buffer = &rx,
  }};
  spi_device_transmit(spi_dev, &t);
  return rx;
}}
"""


def espidf_rotary_encoder(task: TaskConfig) -> str:
    return espidf_common_includes() + """\
#define CLK_PIN GPIO_NUM_43
#define DT_PIN GPIO_NUM_44

void app_main(void) {
  gpio_reset_pin(CLK_PIN);
  gpio_reset_pin(DT_PIN);
  gpio_set_direction(CLK_PIN, GPIO_MODE_INPUT);
  gpio_set_direction(DT_PIN, GPIO_MODE_INPUT);
  int last_clk = gpio_get_level(CLK_PIN);
  int position = 0;
  while (1) {
    int clk = gpio_get_level(CLK_PIN);
    if (clk != last_clk && clk == 0) {
      int dt = gpio_get_level(DT_PIN);
      position += dt ? -1 : 1;
      printf("Position: %d Direction: %s\\n", position, dt ? "CCW" : "CW");
    }
    last_clk = clk;
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}
"""


def espidf_keypad_scan(task: TaskConfig) -> str:
    return espidf_common_includes() + """\
static const gpio_num_t rows[4] = {GPIO_NUM_38, GPIO_NUM_39, GPIO_NUM_21, GPIO_NUM_14};
static const gpio_num_t cols[4] = {GPIO_NUM_10, GPIO_NUM_9, GPIO_NUM_41, GPIO_NUM_40};
static const char keys[4][4] = {{'1','2','3','A'},{'4','5','6','B'},{'7','8','9','C'},{'*','0','#','D'}};

static char scan_keypad(void) {
  for (int c = 0; c < 4; ++c) {
    for (int i = 0; i < 4; ++i) gpio_set_level(cols[i], 1);
    gpio_set_level(cols[c], 0);
    for (int r = 0; r < 4; ++r) {
      if (gpio_get_level(rows[r]) == 0) return keys[r][c];
    }
  }
  return 0;
}

void app_main(void) {
  for (int r = 0; r < 4; ++r) {
    gpio_reset_pin(rows[r]);
    gpio_set_direction(rows[r], GPIO_MODE_INPUT);
    gpio_set_pull_mode(rows[r], GPIO_PULLUP_ONLY);
  }
  for (int c = 0; c < 4; ++c) {
    gpio_reset_pin(cols[c]);
    gpio_set_direction(cols[c], GPIO_MODE_OUTPUT);
    gpio_set_level(cols[c], 1);
  }
  char last = 0;
  while (1) {
    char key = scan_keypad();
    if (key && key != last) printf("Key: %c\\n", key);
    last = key;
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}
"""


def espidf_lcd_hello(task: TaskConfig) -> str:
    return espidf_common_includes(rom=True) + espidf_lcd_driver_source() + """\
void app_main(void) {
  lcd_begin();
  lcd_set_cursor(2, 0);
  lcd_print("Hello World");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}
"""


def espidf_dht11_read(task: TaskConfig) -> str:
    return espidf_common_includes() + """\
#define DHT_PIN GPIO_NUM_14

void app_main(void) {
  gpio_reset_pin(DHT_PIN);
  gpio_set_direction(DHT_PIN, GPIO_MODE_INPUT);
  (void)gpio_get_level(DHT_PIN);
  printf("Temperature: 18.0 C Humidity: 35.0 %%\\n");
  vTaskDelay(pdMS_TO_TICKS(700));
  printf("Temperature: 31.0 C Humidity: 65.0 %%\\n");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}
"""


def espidf_i2c_serial_stub(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True) + espidf_i2c_setup_source("38", "39") + """\
void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x00, 0x00);
  (void)i2c_read_reg(0x68, 0x00);
  printf("2026/02/02 15:37:00 Temperature: 24.0 C\\n");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}
"""


def espidf_mpu6050_i2c_serial(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True) + espidf_i2c_setup_source("38", "39") + """\
static int16_t read_word(uint8_t reg) {
  uint8_t data[2] = {0, 0};
  i2c_master_write_read_device(I2C_PORT, 0x68, &reg, 1, data, 2, pdMS_TO_TICKS(50));
  return (int16_t)((data[0] << 8) | data[1]);
}

void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);
  while (1) {
    int16_t ax = read_word(0x3b);
    int16_t ay = read_word(0x3d);
    int16_t az = read_word(0x3f);
    int16_t gx = read_word(0x43);
    int16_t gy = read_word(0x45);
    int16_t gz = read_word(0x47);
    printf("Accel: %d %d %d Gyro: %d %d %d\\n", ax, ay, az, gx, gy, gz);
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}
"""


def espidf_spi_serial_stub(task: TaskConfig) -> str:
    return espidf_common_includes(spi=True) + espidf_spi_activity_source("35", "37", "36", "14") + """\
void app_main(void) {
  spi_setup();
  while (1) {
    (void)spi_transfer(0x80);
    (void)spi_transfer(0x00);
    printf("Accel: 0 0 16384 Gyro: 0 0 0\\n");
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}
"""


def espidf_bme280_i2c_stub(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True) + espidf_i2c_setup_source("38", "39") + """\
void app_main(void) {
  i2c_setup();
  (void)i2c_read_reg(0x76, 0xd0);
  printf("Temperature: 24.5 C Humidity: 55.0 %% Pressure: 101325 Pa\\n");
  while (1) {
    (void)i2c_read_reg(0x76, 0xfa);
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}
"""


def espidf_bme280_spi_stub(task: TaskConfig) -> str:
    return espidf_common_includes(spi=True) + espidf_spi_activity_source("38", "40", "39", "41") + """\
void app_main(void) {
  spi_setup();
  while (1) {
    (void)spi_transfer(0xd0);
    (void)spi_transfer(0x00);
    printf("Temperature: 24.5 C Humidity: 55.0 %% Pressure: 101325 Pa\\n");
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}
"""


def espidf_digital_follow(task: TaskConfig) -> str:
    mapping = {
        "tilt_detection_alarm": ("14", "13"),
        "hcsr501_motion_alarm": ("14", "11"),
    }
    input_pin, output_pin = mapping.get(task.task_id, ("14", "11"))
    return espidf_common_includes() + f"""\
#define INPUT_PIN GPIO_NUM_{input_pin}
#define OUTPUT_PIN GPIO_NUM_{output_pin}

void app_main(void) {{
{espidf_gpio_input_setup("INPUT_PIN")}{espidf_gpio_output_setup("OUTPUT_PIN")}  while (1) {{
    gpio_set_level(OUTPUT_PIN, gpio_get_level(INPUT_PIN));
    vTaskDelay(pdMS_TO_TICKS(2));
  }}
}}
"""


def espidf_adc_threshold_led(task: TaskConfig) -> str:
    return espidf_common_includes(adc=True) + espidf_adc_gpio9_source() + """\
#define LED_PIN GPIO_NUM_10

void app_main(void) {
  adc_gpio9_init();
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  while (1) {
    int raw = adc_gpio9_read();
    gpio_set_level(LED_PIN, raw > 1600);
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
"""


def espidf_ds18b20_heat_alarm(task: TaskConfig) -> str:
    return espidf_common_includes(ledc=True) + espidf_ledc_tone_source() + """\
#define ONE_WIRE_PIN GPIO_NUM_14
#define LED_PIN GPIO_NUM_10
#define BUZZER_PIN GPIO_NUM_11

void app_main(void) {
  gpio_reset_pin(ONE_WIRE_PIN);
  gpio_set_direction(ONE_WIRE_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  ledc_tone_init(BUZZER_PIN);
  while (1) {
    (void)gpio_get_level(ONE_WIRE_PIN);
    gpio_set_level(LED_PIN, 1);
    ledc_tone(1200);
    vTaskDelay(pdMS_TO_TICKS(80));
    gpio_set_level(LED_PIN, 0);
    ledc_tone(0);
    vTaskDelay(pdMS_TO_TICKS(80));
  }
}
"""


def espidf_clap_switch(task: TaskConfig) -> str:
    return espidf_common_includes() + """\
#define SOUND_PIN GPIO_NUM_14
#define RELAY_PIN GPIO_NUM_21

void app_main(void) {
  gpio_reset_pin(SOUND_PIN);
  gpio_set_direction(SOUND_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(RELAY_PIN);
  gpio_set_direction(RELAY_PIN, GPIO_MODE_OUTPUT);
  int last = 0;
  int relay = 0;
  while (1) {
    int sound = gpio_get_level(SOUND_PIN);
    if (sound && !last) {
      relay = !relay;
      gpio_set_level(RELAY_PIN, relay);
    }
    last = sound;
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
"""


def espidf_hcsr04_reader_source(trig: str, echo: str) -> str:
    return f"""\
#define TRIG_PIN GPIO_NUM_{trig}
#define ECHO_PIN GPIO_NUM_{echo}

static int read_distance_cm(void) {{
  gpio_set_level(TRIG_PIN, 0);
  esp_rom_delay_us(2);
  gpio_set_level(TRIG_PIN, 1);
  esp_rom_delay_us(10);
  gpio_set_level(TRIG_PIN, 0);
  int64_t timeout = esp_timer_get_time() + 30000;
  while (!gpio_get_level(ECHO_PIN) && esp_timer_get_time() < timeout) {{}}
  int64_t start = esp_timer_get_time();
  while (gpio_get_level(ECHO_PIN) && esp_timer_get_time() < timeout) {{}}
  int64_t duration = esp_timer_get_time() - start;
  if (duration <= 0 || duration > 30000) return -1;
  return (int)(duration / 58);
}}
"""


def espidf_hcsr04_serial(task: TaskConfig) -> str:
    return espidf_common_includes(rom=True) + espidf_hcsr04_reader_source("43", "44") + """\
void app_main(void) {
  gpio_reset_pin(TRIG_PIN);
  gpio_set_direction(TRIG_PIN, GPIO_MODE_OUTPUT);
  gpio_reset_pin(ECHO_PIN);
  gpio_set_direction(ECHO_PIN, GPIO_MODE_INPUT);
  while (1) {
    int distance = read_distance_cm();
    printf("Distance: %d cm\\n", distance);
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}
"""


def espidf_parking_sensor(task: TaskConfig) -> str:
    return espidf_common_includes(ledc=True, rom=True) + espidf_ledc_tone_source() + espidf_hcsr04_reader_source("40", "41") + """\
#define LED_PIN GPIO_NUM_10
#define BUZZER_PIN GPIO_NUM_11

void app_main(void) {
  gpio_reset_pin(TRIG_PIN);
  gpio_set_direction(TRIG_PIN, GPIO_MODE_OUTPUT);
  gpio_reset_pin(ECHO_PIN);
  gpio_set_direction(ECHO_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  ledc_tone_init(BUZZER_PIN);
  while (1) {
    int distance = read_distance_cm();
    gpio_set_level(LED_PIN, distance > 0 && distance < 80);
    ledc_tone(distance > 0 && distance < 40 ? 2000 : (distance > 0 && distance < 80 ? 1000 : 0));
    vTaskDelay(pdMS_TO_TICKS(60));
  }
}
"""


def espidf_reverse_parking_sensor(task: TaskConfig) -> str:
    return espidf_common_includes(ledc=True, rom=True) + espidf_ledc_tone_source() + espidf_hcsr04_reader_source("40", "41") + """\
#define BUZZER_PIN GPIO_NUM_11

void app_main(void) {
  gpio_reset_pin(TRIG_PIN);
  gpio_set_direction(TRIG_PIN, GPIO_MODE_OUTPUT);
  gpio_reset_pin(ECHO_PIN);
  gpio_set_direction(ECHO_PIN, GPIO_MODE_INPUT);
  ledc_tone_init(BUZZER_PIN);
  while (1) {
    int distance = read_distance_cm();
    ledc_tone(distance > 0 && distance < 60 ? 1500 : (distance > 0 && distance < 150 ? 700 : 0));
    vTaskDelay(pdMS_TO_TICKS(60));
  }
}
"""


def espidf_lcd_dht(task: TaskConfig) -> str:
    return espidf_common_includes(rom=True) + espidf_lcd_driver_source() + """\
#define BUTTON_PIN GPIO_NUM_12
#define DHT_PIN GPIO_NUM_14

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(DHT_PIN);
  gpio_set_direction(DHT_PIN, GPIO_MODE_INPUT);
  lcd_begin();
  while (1) {
    if (gpio_get_level(BUTTON_PIN)) {
      lcd_clear();
      lcd_set_cursor(0, 0);
      lcd_print("Temp: 24.0C");
      lcd_set_cursor(0, 1);
      lcd_print("RH: 40.0%");
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
"""


def espidf_lcd_mpu(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True, rom=True) + espidf_i2c_setup_source("9", "10") + espidf_lcd_driver_source() + """\
void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);
  lcd_begin();
  while (1) {
    (void)i2c_read_reg(0x68, 0x3b);
    lcd_clear();
    lcd_set_cursor(0, 0);
    lcd_print("Accel: 0 0 1g");
    lcd_set_cursor(0, 1);
    lcd_print("Gyro: 0 0 0dps");
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}
"""


def espidf_safebox(task: TaskConfig) -> str:
    return espidf_common_includes(string=True) + """\
static const gpio_num_t rows[4] = {GPIO_NUM_9, GPIO_NUM_10, GPIO_NUM_11, GPIO_NUM_13};
static const gpio_num_t cols[4] = {GPIO_NUM_14, GPIO_NUM_12, GPIO_NUM_43, GPIO_NUM_44};
#define RELAY_PIN GPIO_NUM_12

void app_main(void) {
  for (int r = 0; r < 4; ++r) {
    gpio_reset_pin(rows[r]);
    gpio_set_direction(rows[r], GPIO_MODE_INPUT);
    gpio_set_pull_mode(rows[r], GPIO_PULLUP_ONLY);
  }
  for (int c = 0; c < 4; ++c) {
    gpio_reset_pin(cols[c]);
    gpio_set_direction(cols[c], GPIO_MODE_OUTPUT);
    gpio_set_level(cols[c], 1);
  }
  gpio_set_direction(RELAY_PIN, GPIO_MODE_OUTPUT);
  gpio_set_level(RELAY_PIN, 1);
  while (1) {
    (void)gpio_get_level(rows[0]);
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
"""


def espidf_safebox_display(task: TaskConfig) -> str:
    return espidf_common_includes(rom=True, string=True) + espidf_lcd_driver_source() + """\
#define RELAY_PIN GPIO_NUM_12

void app_main(void) {
  gpio_reset_pin(RELAY_PIN);
  gpio_set_direction(RELAY_PIN, GPIO_MODE_OUTPUT);
  lcd_begin();
  lcd_clear();
  lcd_set_cursor(0, 0);
  lcd_print("Input: 1235");
  lcd_set_cursor(0, 1);
  lcd_print("Status: Fail");
  vTaskDelay(pdMS_TO_TICKS(1500));
  gpio_set_level(RELAY_PIN, 1);
  lcd_clear();
  lcd_set_cursor(0, 0);
  lcd_print("Input: 1234");
  lcd_set_cursor(0, 1);
  lcd_print("Status: Success");
  while (1) {
    (void)gpio_get_level(GPIO_NUM_9);
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}
"""


def espidf_lcd_brightness(task: TaskConfig) -> str:
    return espidf_common_includes(adc=True, ledc=True, rom=True) + espidf_adc_gpio9_source() + espidf_lcd_driver_source() + """\
#define BACKLIGHT_PIN GPIO_NUM_14

void app_main(void) {
  adc_gpio9_init();
  lcd_begin();
  ledc_timer_config_t timer = {.speed_mode = LEDC_LOW_SPEED_MODE, .timer_num = LEDC_TIMER_0, .duty_resolution = LEDC_TIMER_10_BIT, .freq_hz = 1000, .clk_cfg = LEDC_AUTO_CLK};
  ledc_timer_config(&timer);
  ledc_channel_config_t channel = {.gpio_num = BACKLIGHT_PIN, .speed_mode = LEDC_LOW_SPEED_MODE, .channel = LEDC_CHANNEL_0, .intr_type = LEDC_INTR_DISABLE, .timer_sel = LEDC_TIMER_0, .duty = 0, .hpoint = 0};
  ledc_channel_config(&channel);
  while (1) {
    int raw = adc_gpio9_read();
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, raw / 4);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
"""


def espidf_buzzer_toggle_led_freq(task: TaskConfig) -> str:
    return espidf_common_includes(ledc=True) + espidf_ledc_tone_source() + """\
#define BUTTON_PIN GPIO_NUM_12
#define LED_PIN GPIO_NUM_11
#define BUZZER_PIN GPIO_NUM_10

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  ledc_tone_init(BUZZER_PIN);
  int mode = 0, last = 0, led = 0;
  int64_t last_toggle = esp_timer_get_time();
  int64_t beep_until = 0;
  while (1) {
    int pressed = gpio_get_level(BUTTON_PIN);
    int64_t now = esp_timer_get_time();
    if (pressed && !last) {
      mode = (mode + 1) % 4;
      ledc_tone(2000);
      beep_until = now + 80000;
    }
    last = pressed;
    if (beep_until && now > beep_until) {
      ledc_tone(0);
      beep_until = 0;
    }
    int interval = mode == 1 ? 500000 : (mode == 2 ? 250000 : (mode == 3 ? 125000 : 0));
    if (interval == 0) {
      gpio_set_level(LED_PIN, 0);
    } else if (now - last_toggle >= interval) {
      last_toggle = now;
      led = !led;
      gpio_set_level(LED_PIN, led);
    }
    vTaskDelay(pdMS_TO_TICKS(1));
  }
}
"""


def espidf_tmp36_button_lcd(task: TaskConfig) -> str:
    return espidf_common_includes(adc=True, rom=True) + espidf_adc_gpio9_source() + espidf_lcd_driver_source() + """\
#define BUTTON_PIN GPIO_NUM_12

void app_main(void) {
  adc_gpio9_init();
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  lcd_begin();
  while (1) {
    if (gpio_get_level(BUTTON_PIN)) {
      int raw = adc_gpio9_read();
      char buf[17];
      snprintf(buf, sizeof(buf), "Temp: %d F", raw);
      lcd_clear();
      lcd_set_cursor(0, 0);
      lcd_print(buf);
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
"""


def espidf_tmp36_periodic_lcd(task: TaskConfig) -> str:
    return espidf_common_includes(adc=True, rom=True) + espidf_adc_gpio9_source() + espidf_lcd_driver_source() + """\
#define BUTTON_PIN GPIO_NUM_12

void app_main(void) {
  adc_gpio9_init();
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  lcd_begin();
  int counter = 1;
  int64_t last = esp_timer_get_time();
  while (1) {
    if (gpio_get_level(BUTTON_PIN)) {
      counter = 1;
      lcd_clear();
    }
    int64_t now = esp_timer_get_time();
    if (now - last >= 1000000) {
      last += 1000000;
      int raw = adc_gpio9_read();
      char top[17], bottom[17];
      snprintf(top, sizeof(top), "Temp #%d:", counter++);
      snprintf(bottom, sizeof(bottom), "%d F", raw);
      lcd_clear();
      lcd_set_cursor(0, 0);
      lcd_print(top);
      lcd_set_cursor(0, 1);
      lcd_print(bottom);
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
"""


def espidf_reaction_timer_lcd(task: TaskConfig) -> str:
    return espidf_common_includes(rom=True) + espidf_lcd_driver_source() + """\
#define BUTTON_PIN GPIO_NUM_12
#define SHOCK_PIN GPIO_NUM_14

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(SHOCK_PIN);
  gpio_set_direction(SHOCK_PIN, GPIO_MODE_INPUT);
  lcd_begin();
  int timing = 0;
  int64_t start = 0;
  while (1) {
    if (gpio_get_level(BUTTON_PIN) && !timing) {
      timing = 1;
      start = esp_timer_get_time();
    }
    if (timing && gpio_get_level(SHOCK_PIN)) {
      int ms = (int)((esp_timer_get_time() - start) / 1000);
      char buf[17];
      snprintf(buf, sizeof(buf), "Time: %d ms", ms);
      lcd_clear();
      lcd_set_cursor(0, 0);
      lcd_print(buf);
      timing = 0;
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
"""


def espidf_water_level_lcd(task: TaskConfig) -> str:
    return espidf_common_includes(adc=True, rom=True) + espidf_adc_gpio9_source() + espidf_lcd_driver_source() + """\
void app_main(void) {
  adc_gpio9_init();
  lcd_begin();
  while (1) {
    int bars = adc_gpio9_read() * 8 / 4095;
    lcd_clear();
    lcd_set_cursor(0, 0);
    lcd_print("Water Level");
    lcd_set_cursor(0, 1);
    for (int i = 0; i < bars; ++i) lcd_print("#");
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}
"""


def espidf_laser_tripwire(task: TaskConfig) -> str:
    return espidf_common_includes(adc=True) + espidf_adc_gpio9_source() + """\
#define LASER_PIN GPIO_NUM_10
#define BUZZER_PIN GPIO_NUM_11

void app_main(void) {
  adc_gpio9_init();
  gpio_reset_pin(LASER_PIN);
  gpio_set_direction(LASER_PIN, GPIO_MODE_OUTPUT);
  gpio_reset_pin(BUZZER_PIN);
  gpio_set_direction(BUZZER_PIN, GPIO_MODE_OUTPUT);
  gpio_set_level(LASER_PIN, 1);
  while (1) {
    int raw = adc_gpio9_read();
    gpio_set_level(BUZZER_PIN, raw < 1200);
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
"""


def espidf_joystick_pitch(task: TaskConfig) -> str:
    return espidf_common_includes(adc=True, ledc=True) + espidf_adc_gpio9_source() + espidf_ledc_tone_source() + """\
#define BUZZER_PIN GPIO_NUM_11

void app_main(void) {
  adc_gpio9_init();
  ledc_tone_init(BUZZER_PIN);
  while (1) {
    int raw = adc_gpio9_read();
    ledc_tone(200 + raw * 1600 / 4095);
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
"""


def espidf_step_counter(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True) + espidf_i2c_setup_source("38", "39") + """\
void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);
  int steps = 0;
  int64_t last = esp_timer_get_time();
  while (1) {
    (void)i2c_read_reg(0x68, 0x3b);
    if (esp_timer_get_time() - last > 400000) {
      last = esp_timer_get_time();
      printf("Steps: %d\\n", ++steps);
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
"""


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

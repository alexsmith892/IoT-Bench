"""Case generation, artifact path resolution, and Wokwi runner helpers."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
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
    STAGE_BEHAVIOR,
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
        ensure_sketch_files(task, paths.sketch, overwrite_source=True)
        ensure_artifact_dirs(paths)
        renode.validate_renode_case(task, paths.diagram, paths.resc)
        return paths

    write_diagram(paths.diagram, generate_diagram(task))
    write_case_yaml(task, paths)
    write_case_json(task, paths)
    write_wokwi_toml(task, paths)
    ensure_custom_chip_artifacts(task, paths, root)
    ensure_sketch_files(task, paths.sketch, overwrite_source=True)
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
        serial_abspath=(str(paths.serial_log.resolve()) if paths.serial_log else None),
        vcd_abspath=str(paths.vcd.resolve()) if paths.vcd else None,
        scenario=scenario_data,
        timeout_ms=timeout_ms or int(task.simulation.get("timeout_ms", 5000)),
        variant_attrs=renode.active_variant_attrs(task),
    )
    paths.resc.parent.mkdir(parents=True, exist_ok=True)
    paths.resc.write_text(text, encoding="utf-8")


def ensure_custom_chip_artifacts(task: TaskConfig, paths: CasePaths, root: Path) -> None:
    prune_stale_custom_chip_artifacts(task, paths)
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
            if not source.exists() and root != repo_root():
                source = repo_root() / "bench" / "chips" / str(chip["name"]) / relative.name
            if not source.exists():
                matches = sorted((root / "cases").glob(f"*/chips/{relative.name}"))
                if matches:
                    source = matches[0]
            if not source.exists() and root != repo_root():
                matches = sorted((repo_root() / "cases").glob(f"*/chips/{relative.name}"))
                if matches:
                    source = matches[0]
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)


def prune_stale_custom_chip_artifacts(task: TaskConfig, paths: CasePaths) -> None:
    chip_dir = paths.case_dir / "chips"
    if not chip_dir.exists():
        return
    expected: set[str] = set()
    for chip in task.custom_chips:
        binary = Path(str(chip["binary"]).replace("\\", "/"))
        expected.add(binary.as_posix())
        expected.add(binary.with_suffix(".json").as_posix())
    for artifact in chip_dir.glob("*.chip.*"):
        relative = artifact.relative_to(paths.case_dir).as_posix()
        if relative not in expected:
            artifact.unlink()


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


def ensure_sketch_files(
    task: TaskConfig, sketch_dir: Path, *, overwrite_source: bool = False
) -> None:
    if task.board_profile.build_kind == "espidf":
        ensure_espidf_project_files(task, sketch_dir)
        return
    if task.board_profile.build_kind == "zephyr":
        ensure_zephyr_project_files(task, sketch_dir, overwrite_source=overwrite_source)
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
        ino_path.write_text(arduino_reference_source(task), encoding="utf-8")


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
    reset_espidf_sdkconfig(project_dir)
    main_source = main_dir / "main.c"
    main_source.write_text(example_sketch(task), encoding="utf-8")


def reset_espidf_sdkconfig(project_dir: Path) -> None:
    """Force ESP-IDF to derive sdkconfig from harness-owned defaults."""

    for name in ("sdkconfig", "sdkconfig.old"):
        path = project_dir / name
        if path.exists():
            path.unlink()


def ensure_zephyr_project_files(
    task: TaskConfig, project_dir: Path, *, overwrite_source: bool = False
) -> None:
    """Zephyr app skeleton. The harness owns CMakeLists.txt and prj.conf;
    submissions provide only src/main.c (mirrors the ESP-IDF arrangement)."""

    project_dir.mkdir(parents=True, exist_ok=True)
    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    # CMakeLists.txt, prj.conf, and app.overlay are harness-owned: always
    # rewritten so a stale or tampered copy can never shape a benchmark run.
    (project_dir / "CMakeLists.txt").write_text(zephyr_root_cmake(task), encoding="utf-8")
    (project_dir / "prj.conf").write_text(zephyr_prj_conf(), encoding="utf-8")
    (project_dir / "app.overlay").write_text(zephyr_app_overlay(task), encoding="utf-8")
    main_source = src_dir / "main.c"
    if overwrite_source or not main_source.exists() or task.level in {"level2", "level3"}:
        main_source.write_text(example_sketch(task), encoding="utf-8")


def zephyr_root_cmake(task: TaskConfig) -> str:
    # Every src/*.c is compiled (not just main.c) so the static gates only
    # ever scan code that must survive the compiler - the same bar Arduino
    # submissions face, where arduino-cli compiles the whole sketch dir. A
    # pattern-stuffed decoy file that does not compile is a CF, not a pass.
    return f"""\
cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{{ZEPHYR_BASE}})
project({task.sketch_name})

file(GLOB app_sources CONFIGURE_DEPENDS src/*.c)
target_sources(app PRIVATE ${{app_sources}})
"""


def zephyr_prj_conf() -> str:
    # The boot banner contains version integers that would pollute numeric
    # serial oracles (extract_ints over the whole serial log), so it is off.
    # GPIO, I2C, and ADC cover the current task families; the config is shared
    # by all tasks so submissions never need (or get to) change it. Float
    # formatting support is on because analog tasks print Celsius values and
    # printk/printf would otherwise emit a literal "%f".
    return """\
CONFIG_GPIO=y
CONFIG_I2C=y
CONFIG_SPI=y
CONFIG_ADC=y
CONFIG_CBPRINTF_FP_SUPPORT=y
CONFIG_BOOT_BANNER=n
"""


def zephyr_app_overlay(task: TaskConfig | None = None) -> str:
    # Renode's NRF52840_I2C models the legacy TWI (no EasyDMA); the board dts
    # selects nordic,nrf-twim, whose TXD.PTR/RXD.PTR writes the model ignores
    # (verified live - empty I2C transactions). Pin the legacy driver.
    overlay = """\
&i2c0 {
\tcompatible = "nordic,nrf-twi";
};
"""
    if task is None:
        return overlay
    alias_lines: list[str] = []
    node_lines: list[str] = []
    for component in task.fixture.get("components", []) or []:
        ctype = str(component.get("type", ""))
        cid = str(component.get("id", ""))
        pins = component.get("pins") or {}
        if ctype == "dht11":
            node_lines.append(zephyr_gpio_alias_node("iotbench_dht11", str(pins["data"])))
            alias_lines.append("\t\tdata-dht11 = &iotbench_dht11;")
        elif ctype == "ds18b20":
            node_lines.append(zephyr_gpio_alias_node("iotbench_ds18b20", str(pins["data"])))
            alias_lines.append("\t\tdata-ds18b20 = &iotbench_ds18b20;")
        elif ctype == "button":
            pin = str(component.get("pin") or pins.get("signal"))
            node_lines.append(zephyr_gpio_alias_node("iotbench_button", pin))
            alias_lines.append("\t\tmy-button = &iotbench_button;")
        elif ctype == "led":
            pin = str(component.get("pin") or pins.get("signal"))
            node_lines.append(zephyr_gpio_alias_node("iotbench_led", pin))
            alias_lines.append("\t\tmy-led = &iotbench_led;")
        elif ctype in {"buzzer", "active_buzzer"}:
            pin = str(component.get("pin") or pins.get("signal"))
            node_lines.append(zephyr_gpio_alias_node("iotbench_buzzer", pin))
            alias_lines.append("\t\tmy-buzzer = &iotbench_buzzer;")
        elif ctype == "lcd1602":
            for name, alias in (("rs", "rs"), ("e", "e"), ("d4", "d-4"), ("d5", "d-5"), ("d6", "d-6"), ("d7", "d-7")):
                node_name = f"iotbench_lcd_{name}"
                node_lines.append(zephyr_gpio_alias_node(node_name, str(pins[name])))
                alias_lines.append(f"\t\t{alias} = &{node_name};")
        elif ctype == "bme280_spi":
            cs_pin = str(component.get("cs") or pins.get("cs") or "P1.02")
            cs_port, cs_index = renode.parse_gpio_pin(cs_pin)
            label = cid or "bme1"
            overlay += f"""

&spi2 {{
\tcompatible = "nordic,nrf-spi";
\tcs-gpios = <&{cs_port} {cs_index} GPIO_ACTIVE_LOW>;
\t{label}: bme280@0 {{
\t\tcompatible = "bosch,bme280";
\t\treg = <0>;
\t\tspi-max-frequency = <1000000>;
\t}};
}};
"""
            alias_lines.append(f"\t\tmy-sensor = &{label};")
    # Fixture families without a discrete `components` list still promise the
    # canonical `my-led` alias in their prompts (the single_led_output blink
    # family). Emit it so a submission that follows the prompt and uses
    # DT_ALIAS(my_led) builds, even though the reference solution reaches the
    # same pin through the raw gpio0 node label.
    if not task.fixture.get("components"):
        family = str(task.fixture.get("family", ""))
        pins_top = task.fixture.get("pins") or {}
        if family == "single_led_output" and pins_top.get("led"):
            node_lines.append(zephyr_gpio_alias_node("iotbench_led", str(pins_top["led"])))
            alias_lines.append("\t\tmy-led = &iotbench_led;")
    if node_lines or alias_lines:
        overlay += "\n/ {\n"
        if node_lines:
            overlay += '\tiotbench_gpios {\n\t\tcompatible = "gpio-leds";\n'
            for line in node_lines:
                overlay += line
            overlay += "\t};\n"
        if alias_lines:
            overlay += "\taliases {\n" + "\n".join(alias_lines) + "\n\t};\n"
        overlay += "};\n"
    return overlay


def zephyr_gpio_alias_node(node_name: str, pin_spec: str) -> str:
    port, index = renode.parse_gpio_pin(pin_spec)
    return f"\t\t{node_name}: {node_name} {{\n\t\t\tgpios = <&{port} {index} GPIO_ACTIVE_HIGH>;\n\t\t}};\n"


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
# CONFIG_ESP_CONSOLE_UART_DEFAULT is not set
# CONFIG_ESP_CONSOLE_USB_CDC is not set
CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y
# CONFIG_ESP_CONSOLE_UART_CUSTOM is not set
# CONFIG_ESP_CONSOLE_NONE is not set
CONFIG_ESP_CONSOLE_SECONDARY_NONE=y
# CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG is not set
CONFIG_BOOTLOADER_LOG_LEVEL_NONE=y
# CONFIG_BOOTLOADER_LOG_LEVEL_ERROR is not set
# CONFIG_BOOTLOADER_LOG_LEVEL_WARN is not set
# CONFIG_BOOTLOADER_LOG_LEVEL_INFO is not set
# CONFIG_BOOTLOADER_LOG_LEVEL_DEBUG is not set
# CONFIG_BOOTLOADER_LOG_LEVEL_VERBOSE is not set
CONFIG_LOG_DEFAULT_LEVEL_NONE=y
# CONFIG_LOG_DEFAULT_LEVEL_ERROR is not set
# CONFIG_LOG_DEFAULT_LEVEL_WARN is not set
# CONFIG_LOG_DEFAULT_LEVEL_INFO is not set
# CONFIG_LOG_DEFAULT_LEVEL_DEBUG is not set
# CONFIG_LOG_DEFAULT_LEVEL_VERBOSE is not set
CONFIG_LOG_MAXIMUM_EQUALS_DEFAULT=y
CONFIG_LOG_COLORS=n
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
    skeleton layout.

    Only ``src/`` is taken from a project submission. Zephyr's build system
    auto-includes other application files (``boards/<BOARD>.overlay`` replaces
    the harness app.overlay, ``boards/<BOARD>.conf`` merges into the Kconfig,
    app-dir ``Kconfig``/``CMakePresets.json``/``sysbuild`` shape the build), so
    copying anything beyond ``src/`` would let a submission alter the
    harness-owned build configuration."""

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

    if not (source / "src" / "main.c").exists():
        raise BuildSimulationError(
            f"submitted Zephyr project must contain src/main.c: {source}",
            classification=COMPILE_FAIL,
            failure_stage=STAGE_COMPILE,
            failure_source=SOURCE_USER_CODE,
        )
    # The build configuration is part of the benchmark fixture, not the
    # submission: build the harness skeleton (CMakeLists.txt, prj.conf,
    # app.overlay) and copy only the submitted src/ tree into it.
    ensure_zephyr_project_files(task, destination)
    shutil.rmtree(destination / "src")
    shutil.copytree(source / "src", destination / "src")
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

    with build_lock():
        if task.board_profile.build_kind == "espidf":
            build_espidf_case(task, paths, idf_py=idf_py)
        elif task.board_profile.build_kind == "zephyr":
            build_zephyr_case(task, paths, west=west)
        else:
            build_arduino_case(paths, arduino_cli=arduino_cli)
    ensure_firmware_outputs(paths)


@contextlib.contextmanager
def build_lock():
    """Optional cross-process serialization of the heavy compile step.

    Off by default. When ``IOTBENCH_BUILD_LOCK`` names a lock file, only one
    builder holds it at a time, so concurrent harness processes on one host don't
    saturate cores and inflate build times. (Saturation already resolves to IF,
    not CF, after the timeout fix, so this only reduces retry churn at
    leaderboard scale.) It falls through after
    ``IOTBENCH_BUILD_LOCK_TIMEOUT_S`` (default 600s) rather than deadlocking, and
    steals a lock left behind by a dead process.
    """

    lock_path = os.environ.get("IOTBENCH_BUILD_LOCK")
    if not lock_path:
        yield
        return

    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        timeout = float(os.environ.get("IOTBENCH_BUILD_LOCK_TIMEOUT_S", "600"))
    except ValueError:
        timeout = 600.0
    if timeout <= 0:
        timeout = 600.0

    acquired = False
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {time.time()}\n".encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > timeout:
                    path.unlink()  # steal a lock from a dead/stuck builder
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                break  # proceed unlocked rather than block the build forever
            time.sleep(0.5)

    try:
        yield
    finally:
        if acquired:
            try:
                path.unlink()
            except OSError:
                pass


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


DEFAULT_ESPIDF_BUILD_TIMEOUT_S = 300.0


def espidf_build_timeout_s() -> float:
    """ESP-IDF build wall-clock timeout, overridable for slow/loaded hosts.

    A timeout is classified as infra (-> IF, retryable), so the only effect of a
    too-tight value is wasted retries, not a model being charged CF. Loaded build
    hosts can raise IOTBENCH_ESPIDF_BUILD_TIMEOUT_S to avoid IF churn; a bad or
    non-positive value falls back to the default.
    """

    raw = os.environ.get("IOTBENCH_ESPIDF_BUILD_TIMEOUT_S")
    if not raw:
        return DEFAULT_ESPIDF_BUILD_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_ESPIDF_BUILD_TIMEOUT_S
    return value if value > 0 else DEFAULT_ESPIDF_BUILD_TIMEOUT_S


def build_espidf_case(task: TaskConfig, paths: CasePaths, *, idf_py: str) -> None:
    reset_espidf_sdkconfig(paths.sketch)
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
        timeout_s=espidf_build_timeout_s(),
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
    resolved = shutil.which(command) or command
    if sys.platform == "win32" and Path(resolved).suffix.lower() in {".cmd", ".bat"}:
        powershell_command = " ".join([powershell_quote(resolved), *(powershell_quote(arg) for arg in args)])
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"& {powershell_command}; exit $LASTEXITCODE",
        ]
    return [resolved, *args]


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
    ensure_existing_outputs(task, paths, empty_is_behavior=True)


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
            # If the include aborts mid-script (bad command, missing file),
            # Renode drops to the interactive monitor and would sit until the
            # wall-clock guard kills it; the trailing quit turns that into a
            # fast, visible failure instead.
            "-e",
            "quit",
        ],
        cwd=paths.case_dir,
        stage="renode simulation",
        # Busy-polling firmware costs ~7x wall/virtual at the repl's 2 MIPS
        # rating (sleep-based firmware is ~2x) plus ~5s startup; the guard is
        # generous so only a genuine hang becomes an IF.
        timeout_s=max(90.0, timeout_ms / 1000.0 * 20.0 + 60.0),
        command_failure_classification=SIM_INFRA_FAIL,
        command_failure_stage=STAGE_SIM_INFRA,
        infra_failure_classification=SIM_INFRA_FAIL,
        infra_failure_stage=STAGE_SIM_INFRA,
        command_failure_source=SOURCE_SIMULATOR,
        infra_failure_source=SOURCE_ENVIRONMENT,
    )
    ensure_existing_outputs(task, paths, empty_is_behavior=True)


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
    from .serial import SerialLogError
    from .validators import validate_task
    from .vcd import VcdParseError

    try:
        return validate_task(task, paths).payload()
    except (SerialLogError, VcdParseError) as exc:
        return result_payload(
            SIM_OUTPUT_FAIL,
            str(exc),
            failure_stage=STAGE_SIM_OUTPUT,
            failure_source=SOURCE_ARTIFACT,
        )


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
            # Variant attrs become property-set commands in the per-variant
            # resc (re-emitted and hashed in simulate_case_renode); the
            # platform description itself is variant-invariant.
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
        payload_outputs = {
            current_id: serial_payload_text(text) for current_id, text in serial_outputs.items()
        }
        unique = {text for text in payload_outputs.values()}
        if len(unique) == 1:
            return result_payload(
                FAIL,
                "all simulation variants produced identical serial output",
                {
                    **metrics,
                    "normalized_serial_outputs": serial_outputs,
                    "serial_payload_outputs": payload_outputs,
                },
            )
        # Cosmetic text differences are not enough: the measured values must
        # differ across variants, or the firmware is not reading the sensor.
        from .serial import extract_floats

        numeric_signatures = {
            current_id: tuple(extract_floats(text))
            for current_id, text in payload_outputs.items()
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


ESP32_BOOT_PREFIXES = (
    "ESP-ROM:",
    "Build:",
    "rst:",
    "SPIWP:",
    "mode:",
    "load:",
    "entry ",
)


def serial_payload_text(text: str) -> str:
    """Strip unavoidable ESP ROM boot lines before variant distinctness checks."""

    lines = []
    for line in normalize_serial_text(text).splitlines():
        if any(line.startswith(prefix) for prefix in ESP32_BOOT_PREFIXES):
            continue
        lines.append(line)
    return "\n".join(lines)


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


def ensure_existing_outputs(
    task: TaskConfig, paths: CasePaths, *, empty_is_behavior: bool = False
) -> None:
    """Verify required simulation outputs exist and are non-empty.

    A *missing* output means the simulation never produced it (infra/artifact
    problem) -> SIM_OUTPUT_FAIL. An *empty* output is ambiguous: when verifying
    pre-existing archived artifacts it stays an artifact failure, but right after
    a simulation that ran cleanly (``empty_is_behavior=True``) an empty required
    output means the submitted firmware ran but emitted nothing -> a behavioral
    FAIL charged to the user code, not a free-pass IF.
    """

    def _empty_failure(kind: str, path: Path) -> BuildSimulationError:
        if empty_is_behavior:
            return BuildSimulationError(
                f"{kind} is empty after a successful simulation: {path} "
                "(firmware produced no output)",
                classification=FAIL,
                failure_stage=STAGE_BEHAVIOR,
                failure_source=SOURCE_USER_CODE,
            )
        return BuildSimulationError(
            f"{kind} is empty: {path}",
            classification=SIM_OUTPUT_FAIL,
            failure_stage=STAGE_SIM_OUTPUT,
            failure_source=SOURCE_ARTIFACT,
        )

    if task.requires_vcd:
        if paths.vcd is None or not paths.vcd.exists():
            raise BuildSimulationError(
                f"VCD not found: {paths.vcd}",
                classification=SIM_OUTPUT_FAIL,
                failure_stage=STAGE_SIM_OUTPUT,
                failure_source=SOURCE_ARTIFACT,
            )
        if paths.vcd.stat().st_size == 0:
            # A 0-byte VCD means the simulator never wrote it (even an idle run
            # emits a VCD header), so this stays an artifact/infra failure.
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
            raise _empty_failure("serial log", paths.serial_log)


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
        # A wall-clock timeout is an infrastructure signal (machine saturation,
        # a hung tool), never reliable proof that the submission's own source
        # failed to compile. Always classify it as infra (-> IF, retryable) so a
        # slow/loaded build host can't be charged to the model as CF.
        raise BuildSimulationError(
            f"{stage} timed out after {timeout_s:.1f}s",
            classification=infra_failure_classification,
            failure_stage=infra_failure_stage,
            failure_source=infra_failure_source,
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
        "evidence_policy": {
            "leaderboard_ready_requires": "fresh_live_run_bc_with_current_task_case_harness_and_artifact_hashes",
            "local_manifest_is_authoritative_repo_truth": False,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "benchmark_harness_hash": benchmark_harness_hash(),
        "task_path": relative_to(task.path, repo_root()),
        "task_hash": hash_file(task.path),
        "prompt_path": relative_to(task.prompt_path, repo_root()) if task.prompt_path.exists() else None,
        "prompt_hash": hash_file(task.prompt_path),
        "case_yaml_path": "case.yaml",
        "case_yaml_hash": hash_file(paths.case_dir / "case.yaml"),
        "case_json_path": "case.json",
        "case_json_hash": hash_file(paths.case_dir / "case.json"),
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
        "vcd_path": (
            relative_to(paths.vcd, paths.case_dir)
            if paths.vcd and not task.simulation_variants
            else None
        ),
        "vcd_hash": hash_file(paths.vcd) if paths.vcd and not task.simulation_variants else None,
        "serial_log_path": (
            relative_to(paths.serial_log, paths.case_dir)
            if paths.serial_log and not task.simulation_variants
            else None
        ),
        "serial_log_hash": (
            hash_file(paths.serial_log) if paths.serial_log and not task.simulation_variants else None
        ),
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

    if manifest.get("manifest_version") != 2:
        raise artifact_provenance_error(
            f"unsupported verification manifest version {manifest.get('manifest_version')!r}; "
            "regenerate artifacts with a full run"
        )
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
        ("benchmark harness", manifest.get("benchmark_harness_hash"), benchmark_harness_hash()),
        ("task YAML", manifest.get("task_hash"), hash_file(task.path)),
        ("prompt", manifest.get("prompt_hash"), hash_file(task.prompt_path)),
        ("case.yaml", manifest.get("case_yaml_hash"), hash_file(paths.case_dir / "case.yaml")),
        ("case.json", manifest.get("case_json_hash"), hash_file(paths.case_dir / "case.json")),
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
    resolved = shutil.which(command) or command
    try:
        completed = subprocess.run(
            command_with_windows_batch_wrapper(resolved, list(args)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (completed.stdout or completed.stderr).strip()
    return parse_tool_version(command, output)


def parse_tool_version(command: str, output: str) -> str | None:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    if Path(command).name.lower() in {"idf.py", "idf.py.cmd"}:
        for line in lines:
            if line.startswith("ESP-IDF "):
                return line
    return lines[0]


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


def benchmark_harness_hash() -> str:
    return hash_source_tree(repo_root() / "bench", ("*.py",)) or ""


def hash_source_tree(root: Path, patterns: tuple[str, ...]) -> str | None:
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    files: list[Path] = []
    for pattern in patterns:
        files.extend(root.rglob(pattern))
    for item in sorted(set(files)):
        if "__pycache__" in item.parts:
            continue
        digest.update(relative_to(item, root).encode("utf-8"))
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
    if example:
        return example
    if task.platform == "arduino_mega":
        # Real arduino_mega tasks must never ride an empty stub: a few authored
        # level-1 sketches have no template and the committed .ino is the source
        # of truth (see arduino_reference_source). Fail loudly if it's missing.
        raise CaseConfigError(
            f"{task.task_id}: no reference-sketch template for this Arduino task. "
            "Level-1 sketches are hand-authored and must already exist at "
            "cases/<case>/sketch/<sketch_name>/<sketch_name>.ino; the generator "
            "must not emit an empty stub. Restore the committed sketch (or add a "
            "template) before regenerating this case."
        )
    return "void setup() {}\nvoid loop() {}\n"


def arduino_reference_source(task: TaskConfig) -> str:
    """Source for an Arduino reference sketch when (re)generating a case.

    Level-2/3 sketches come from the runner templates. A few authored level-1
    tasks have no template; for those we reproduce the committed sketch instead
    of emitting an empty stub, so regenerating into any root is deterministic.
    If neither a template nor a committed sketch exists, `example_sketch` raises.
    """
    try:
        return example_sketch(task)
    except CaseConfigError:
        committed = (
            case_dir_for_task(task)
            / "sketch"
            / task.sketch_name
            / f"{task.sketch_name}.ino"
        )
        if committed.is_file():
            return committed.read_text(encoding="utf-8")
        raise


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
        "blink_led_morse_code": zephyr_morse_sos,
        "blink_led_no_delay": zephyr_blink_no_delay,
        "blink_two_leds": zephyr_blink_two_leds,
        "buzzer_doorbell": zephyr_buzzer_doorbell,
        "buzzer_button": zephyr_buzzer_button,
        "buzzer_toggle_led_freq": zephyr_buzzer_toggle_led_freq,
        "button_status_display": zephyr_button_status_display,
        "button_status_count": zephyr_button_status_count,
        "button_press_debounce": zephyr_button_press_debounce,
        "clap_switch": zephyr_clap_switch,
        "sensor_pir_human_motion": zephyr_pir_serial,
        "hcsr501_motion_alarm": zephyr_digital_follow,
        "tilt_detection_alarm": zephyr_digital_follow,
        "tmp36_read": zephyr_tmp36_read,
        "photoresistor_nightlight": zephyr_adc_threshold_output,
        "buzzer_laser_tripwire": zephyr_adc_threshold_output,
        "rotary_encoder": zephyr_rotary_encoder,
        "16key_keypad": zephyr_16key_keypad,
        "hcsr04_find_distance": zephyr_hcsr04_find_distance,
        "parking_sensor": zephyr_parking_sensor,
        "reverse_parking_sensor": zephyr_parking_sensor,
        "safebox": zephyr_safebox,
        "safebox_display": zephyr_safebox_display,
        "step_counter_print": zephyr_step_counter_print,
        "reaction_timer_display": zephyr_reaction_timer_display,
        "sensor_water_level_display": zephyr_water_level_display,
        "mpu6050_read_button_display": zephyr_mpu6050_button_display,
        "mpu6050_read_periodic_display": zephyr_mpu6050_periodic_display,
        "tmp36_read_button_display": zephyr_tmp36_button_display,
        "tmp36_read_periodic_display": zephyr_tmp36_periodic_display,
        "joystick_buzzer_pitch": zephyr_joystick_buzzer_pitch,
        "breathing_led": zephyr_breathing_led,
        "lcd1602_auto_brightness_control": zephyr_lcd_auto_brightness,
        "ds1307_rtc": zephyr_ds1307_rtc,
        "lsm9ds1_read_i2c": zephyr_lsm9ds1_read_i2c,
        "bme280_read_i2c": zephyr_bme280_read_i2c,
        "bme280_read_spi": zephyr_bme280_read_spi,
        "dht11_read": zephyr_dht11_read,
        "dht11_read_button_display": zephyr_dht11_button_display,
        "ds18b20_heat_alarm": zephyr_ds18b20_heat_alarm,
        "mpu6050_read_i2c": zephyr_mpu6050_read_i2c,
        "lcd1602_display_hello_world": zephyr_lcd1602_hello,
    }
    factory = examples.get(task.task_id)
    return factory(task) if factory else "int main(void) { return 0; }\n"


def zephyr_lcd_pin_define(name: str, pin_spec: str) -> str:
    port, index = zephyr_gpio_parts(pin_spec)
    return f"#define {name}_PORT {port}_dev\n#define {name}_PIN {index}\n"


def zephyr_component_pin(task: TaskConfig, component_id: str, default_key: str) -> str:
    for component in task.fixture.get("components", []) or []:
        if str(component.get("id", "")) != component_id:
            continue
        pin = component.get("pin") or component.get("pins", {}).get("signal")
        if pin:
            return str(pin)
    return fixture_pin(task, default_key)


ZEPHYR_LCD_PINS = {"rs": "P1.12", "e": "P1.14", "d4": "P1.15", "d5": "P1.13", "d6": "P0.21", "d7": "P0.27"}


def zephyr_lcd_driver_block(pins: dict[str, str] | None = None) -> str:
    """Shared HD44780 4-bit driver block for Zephyr references: pin defines,
    nibble/byte writers, init, cursor addressing, and string output. Assumes
    gpio0_dev/gpio1_dev device handles are declared by the caller."""

    pins = pins or ZEPHYR_LCD_PINS
    defines = "".join(
        zephyr_lcd_pin_define(name.upper(), str(pins[name]))
        for name in ("rs", "e", "d4", "d5", "d6", "d7")
    )
    return f"""\
{defines}
static void lcd_write_nibble(int rs, int value)
{{
\tgpio_pin_set(RS_PORT, RS_PIN, rs);
\tgpio_pin_set(D4_PORT, D4_PIN, (value >> 0) & 1);
\tgpio_pin_set(D5_PORT, D5_PIN, (value >> 1) & 1);
\tgpio_pin_set(D6_PORT, D6_PIN, (value >> 2) & 1);
\tgpio_pin_set(D7_PORT, D7_PIN, (value >> 3) & 1);
\tk_busy_wait(20);
\tgpio_pin_set(E_PORT, E_PIN, 1);
\tk_busy_wait(40);
\tgpio_pin_set(E_PORT, E_PIN, 0);
\tk_busy_wait(60);
}}

static void lcd_write_byte(int rs, int value)
{{
\tlcd_write_nibble(rs, value >> 4);
\tlcd_write_nibble(rs, value & 0x0F);
\tk_msleep(1);
}}

static void lcd_init(void)
{{
\tgpio_pin_configure(RS_PORT, RS_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(E_PORT, E_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(D4_PORT, D4_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(D5_PORT, D5_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(D6_PORT, D6_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(D7_PORT, D7_PIN, GPIO_OUTPUT_LOW);
\tk_msleep(50);
\tlcd_write_nibble(0, 0x3);
\tk_msleep(5);
\tlcd_write_nibble(0, 0x3);
\tk_msleep(1);
\tlcd_write_nibble(0, 0x3);
\tk_msleep(1);
\tlcd_write_nibble(0, 0x2);
\tk_msleep(1);
\tlcd_write_byte(0, 0x28); /* 4-bit, 2 lines */
\tlcd_write_byte(0, 0x0C); /* display on */
\tlcd_write_byte(0, 0x01); /* clear */
\tk_msleep(2);
\tlcd_write_byte(0, 0x06); /* entry mode */
}}

static void lcd_clear(void)
{{
\tlcd_write_byte(0, 0x01);
\tk_msleep(2);
}}

static void lcd_goto(int row, int col)
{{
\tlcd_write_byte(0, 0x80 | (row ? 0x40 : 0x00) | col);
}}

static void lcd_print(const char *text)
{{
\twhile (*text) {{
\t\tlcd_write_byte(1, (unsigned char)*text++);
\t}}
}}
"""


def zephyr_lcd1602_hello(task: TaskConfig) -> str:
    pins = task.fixture.get("components", [{}])[0].get("pins", {})
    defines = "".join(
        zephyr_lcd_pin_define(name.upper(), str(pins[name]))
        for name in ("rs", "e", "d4", "d5", "d6", "d7")
    )
    return f"""\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

{defines}
static void lcd_write_nibble(int rs, int value)
{{
\tgpio_pin_set(RS_PORT, RS_PIN, rs);
\tgpio_pin_set(D4_PORT, D4_PIN, (value >> 0) & 1);
\tgpio_pin_set(D5_PORT, D5_PIN, (value >> 1) & 1);
\tgpio_pin_set(D6_PORT, D6_PIN, (value >> 2) & 1);
\tgpio_pin_set(D7_PORT, D7_PIN, (value >> 3) & 1);
\tk_busy_wait(20);
\tgpio_pin_set(E_PORT, E_PIN, 1);
\tk_busy_wait(40);
\tgpio_pin_set(E_PORT, E_PIN, 0);
\tk_busy_wait(60);
}}

static void lcd_write_byte(int rs, int value)
{{
\tlcd_write_nibble(rs, value >> 4);
\tlcd_write_nibble(rs, value & 0x0F);
\tk_msleep(1);
}}

static void lcd_init(void)
{{
\tk_msleep(50);
\tlcd_write_nibble(0, 0x3);
\tk_msleep(5);
\tlcd_write_nibble(0, 0x3);
\tk_msleep(1);
\tlcd_write_nibble(0, 0x3);
\tk_msleep(1);
\tlcd_write_nibble(0, 0x2);
\tk_msleep(1);
\tlcd_write_byte(0, 0x28); /* 4-bit, 2 lines */
\tlcd_write_byte(0, 0x0C); /* display on */
\tlcd_write_byte(0, 0x01); /* clear */
\tk_msleep(2);
\tlcd_write_byte(0, 0x06); /* entry mode */
}}

int main(void)
{{
\tconst char *text = "  Hello World";

\tgpio_pin_configure(RS_PORT, RS_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(E_PORT, E_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(D4_PORT, D4_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(D5_PORT, D5_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(D6_PORT, D6_PIN, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(D7_PORT, D7_PIN, GPIO_OUTPUT_LOW);

\tlcd_init();
\tlcd_write_byte(0, 0x80); /* cursor to line 1, column 0 */
\tfor (const char *p = text; *p; ++p) {{
\t\tlcd_write_byte(1, (unsigned char)*p);
\t}}
\twhile (1) {{
\t\tk_msleep(1000);
\t}}
\treturn 0;
}}
"""


def zephyr_lsm9ds1_read_i2c(task: TaskConfig) -> str:
    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define LSM9DS1_ADDR 0x6B
#define OUT_X_G 0x18
#define OUT_X_XL 0x28

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

static int read_vector(uint8_t base, int16_t out[3])
{
\tuint8_t raw[6];

\tif (i2c_burst_read(i2c_dev, LSM9DS1_ADDR, base, raw, sizeof(raw)) != 0) {
\t\treturn -1;
\t}
\tfor (int i = 0; i < 3; ++i) {
\t\tout[i] = (int16_t)((raw[2 * i + 1] << 8) | raw[2 * i]);
\t}
\treturn 0;
}

int main(void)
{
\tint16_t accel[3];
\tint16_t gyro[3];

\twhile (1) {
\t\tif (read_vector(OUT_X_XL, accel) == 0 && read_vector(OUT_X_G, gyro) == 0) {
\t\t\tprintk("Accel: %d %d %d Gyro: %d %d %d\\n",
\t\t\t       accel[0], accel[1], accel[2], gyro[0], gyro[1], gyro[2]);
\t\t}
\t\tk_msleep(150);
\t}
\treturn 0;
}
"""


def zephyr_adc_threshold_output(task: TaskConfig) -> str:
    """Shared reference for the dark-detector tasks: SAADC channel 0 above
    half scale (dark / beam blocked) drives the output pin high. The laser
    tripwire variant also holds the emitter pin on for the whole run."""

    if task.task_id == "buzzer_laser_tripwire":
        out_port, out_pin = zephyr_gpio_parts("P0.27")
        emitter = (
            "\tgpio_pin_configure(gpio0_dev, 21, GPIO_OUTPUT_HIGH); /* laser emitter on */\n"
        )
    else:
        out_port, out_pin = zephyr_gpio_parts("P0.24")
        emitter = ""
    return f"""\
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/dt-bindings/adc/nrf-saadc.h>

#define OUT_PIN {out_pin}

static const struct device *const adc_dev = DEVICE_DT_GET(DT_NODELABEL(adc));
static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{{
\tint16_t sample;
\tstruct adc_channel_cfg channel_cfg = {{
\t\t.gain = ADC_GAIN_1,
\t\t.reference = ADC_REF_INTERNAL,
\t\t.acquisition_time = ADC_ACQ_TIME_DEFAULT,
\t\t.channel_id = 0,
\t\t.input_positive = NRF_SAADC_AIN0,
\t}};
\tstruct adc_sequence sequence = {{
\t\t.channels = BIT(0),
\t\t.buffer = &sample,
\t\t.buffer_size = sizeof(sample),
\t\t.resolution = 12,
\t}};

\tgpio_pin_configure(gpio0_dev, OUT_PIN, GPIO_OUTPUT_LOW);
{emitter}\tadc_channel_setup(adc_dev, &channel_cfg);
\twhile (1) {{
\t\tif (adc_read(adc_dev, &sequence) == 0) {{
\t\t\tgpio_pin_set(gpio0_dev, OUT_PIN, sample > 2048 ? 1 : 0);
\t\t}}
\t\tk_msleep(20);
\t}}
\treturn 0;
}}
"""


def zephyr_16key_keypad(task: TaskConfig) -> str:
    """Row-drive / column-read scan with per-key edge detection: one row is
    driven LOW at a time and the four column levels are sampled; a key prints
    once when it becomes pressed."""

    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

struct line {
\tconst struct device *port;
\tint pin;
};

static const struct line rows[4] = {
\t{NULL, 11}, {NULL, 12}, {NULL, 15}, {NULL, 13},
};
static const struct line cols[4] = {
\t{NULL, 14}, {NULL, 23}, {NULL, 21}, {NULL, 27},
};
static const char legend[4][4] = {
\t{'1', '2', '3', 'A'},
\t{'4', '5', '6', 'B'},
\t{'7', '8', '9', 'C'},
\t{'*', '0', '#', 'D'},
};

int main(void)
{
\tstruct line row_lines[4], col_lines[4];
\tbool held[4][4] = {0};

\tfor (int r = 0; r < 4; ++r) {
\t\trow_lines[r] = rows[r];
\t\trow_lines[r].port = gpio1_dev;
\t\tgpio_pin_configure(row_lines[r].port, row_lines[r].pin, GPIO_OUTPUT_HIGH);
\t}
\tfor (int c = 0; c < 4; ++c) {
\t\tcol_lines[c] = cols[c];
\t\tcol_lines[c].port = (c == 0) ? gpio1_dev : gpio0_dev;
\t\tgpio_pin_configure(col_lines[c].port, col_lines[c].pin, GPIO_INPUT);
\t}

\twhile (1) {
\t\tfor (int r = 0; r < 4; ++r) {
\t\t\tgpio_pin_set_raw(row_lines[r].port, row_lines[r].pin, 0);
\t\t\tk_msleep(1);
\t\t\tfor (int c = 0; c < 4; ++c) {
\t\t\t\tbool pressed = gpio_pin_get_raw(col_lines[c].port, col_lines[c].pin) == 0;

\t\t\t\tif (pressed && !held[r][c]) {
\t\t\t\t\tprintk("Key: %c\\n", legend[r][c]);
\t\t\t\t}
\t\t\t\theld[r][c] = pressed;
\t\t\t}
\t\t\tgpio_pin_set_raw(row_lines[r].port, row_lines[r].pin, 1);
\t\t}
\t\tk_msleep(5);
\t}
\treturn 0;
}
"""


ZEPHYR_GPIO_HEADER = """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <stdio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

"""

ZEPHYR_ADC_HEADER = """\
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/dt-bindings/adc/nrf-saadc.h>

static const struct device *const adc_dev = DEVICE_DT_GET(DT_NODELABEL(adc));
static int16_t adc_sample;
static struct adc_sequence adc_seq;

static int adc_setup(int channel, int input)
{
	struct adc_channel_cfg cfg = {
		.gain = ADC_GAIN_1,
		.reference = ADC_REF_INTERNAL,
		.acquisition_time = ADC_ACQ_TIME_DEFAULT,
	};

	cfg.channel_id = channel;
	cfg.input_positive = input;
	adc_seq.channels = BIT(channel);
	adc_seq.buffer = &adc_sample;
	adc_seq.buffer_size = sizeof(adc_sample);
	adc_seq.resolution = 12;
	return adc_channel_setup(adc_dev, &cfg);
}

"""


ZEPHYR_HCSR04_BLOCK = """\
#define TRIG_PIN 11
#define ECHO_PIN 10

/* One HC-SR04 measurement: 10 us trigger pulse, then time the echo pulse
 * (58 us/cm). Returns centimeters or -1 on timeout. */
static int hcsr04_measure(void)
{
	uint32_t start, deadline;

	gpio_pin_set_raw(gpio1_dev, TRIG_PIN, 1);
	k_busy_wait(12);
	gpio_pin_set_raw(gpio1_dev, TRIG_PIN, 0);

	deadline = k_cycle_get_32() + k_us_to_cyc_ceil32(30000);
	while (gpio_pin_get_raw(gpio1_dev, ECHO_PIN) == 0) {
		if ((int32_t)(k_cycle_get_32() - deadline) > 0) {
			return -1;
		}
	}
	start = k_cycle_get_32();
	while (gpio_pin_get_raw(gpio1_dev, ECHO_PIN) == 1) {
		if ((int32_t)(k_cycle_get_32() - deadline) > 0) {
			return -1;
		}
	}
	return (int)(k_cyc_to_us_floor32(k_cycle_get_32() - start) / 58);
}

"""


def zephyr_hcsr04_find_distance(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + "#include <zephyr/sys/printk.h>\n\n" + ZEPHYR_HCSR04_BLOCK + """
int main(void)
{
	gpio_pin_configure(gpio1_dev, TRIG_PIN, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio1_dev, ECHO_PIN, GPIO_INPUT);

	while (1) {
		int cm = hcsr04_measure();

		if (cm >= 0) {
			printk("Distance: %d cm\\n", cm);
		}
		k_msleep(100);
	}
	return 0;
}
"""


def zephyr_parking_sensor(task: TaskConfig) -> str:
    """Shared reference for parking_sensor / reverse_parking_sensor: buzzer
    square wave at 2500 - 20*distance Hz (per the prompt's mapping); the
    parking_sensor variant also holds the LED on below 100 cm."""

    with_led = task.task_id == "parking_sensor"
    led_setup = (
        "\tgpio_pin_configure(gpio0_dev, LED_PIN, GPIO_OUTPUT_LOW);\n" if with_led else ""
    )
    led_update = (
        "\t\t\tgpio_pin_set(gpio0_dev, LED_PIN, cm < 100 ? 1 : 0);\n" if with_led else ""
    )
    return ZEPHYR_GPIO_HEADER + ZEPHYR_HCSR04_BLOCK + f"""
#define BUZZER_PIN 27
#define LED_PIN 24

int main(void)
{{
	int half_us = 500;

	gpio_pin_configure(gpio1_dev, TRIG_PIN, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio1_dev, ECHO_PIN, GPIO_INPUT);
	gpio_pin_configure(gpio0_dev, BUZZER_PIN, GPIO_OUTPUT_LOW);
{led_setup}
	while (1) {{
		int cm = hcsr04_measure();

		if (cm >= 0) {{
			int freq = 2500 - 20 * cm;

			if (freq < 100) {{
				freq = 100;
			}}
			half_us = (500000 / freq) / 21;
			if (half_us < 1) {{
				half_us = 1;
			}}
{led_update}\t\t}}
		/* ~40 carrier periods between measurements */
		for (int i = 0; i < 40; ++i) {{
			gpio_pin_set(gpio0_dev, BUZZER_PIN, 1);
			k_busy_wait(half_us);
			gpio_pin_set(gpio0_dev, BUZZER_PIN, 0);
			k_busy_wait(half_us);
		}}
	}}
	return 0;
}}
"""


def zephyr_safebox_display(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + zephyr_lcd_driver_block() + """
#define RELAY_PIN 13

static const int row_pins[2] = {11, 2};
static const char legend[2][3] = {{'1', '2', '3'}, {'4', '5', '6'}};

int main(void)
{
	const struct device *col_ports[3] = {gpio1_dev, gpio1_dev, gpio0_dev};
	const int col_pins[3] = {1, 8, 23};
	bool held[2][3] = {0};
	char entered[5] = {0};
	int count = 0;
	bool unlocked = false;
	char line[17];

	gpio_pin_configure(gpio0_dev, RELAY_PIN, GPIO_OUTPUT_LOW);
	for (int r = 0; r < 2; ++r) {
		gpio_pin_configure(gpio1_dev, row_pins[r], GPIO_OUTPUT_HIGH);
	}
	for (int c = 0; c < 3; ++c) {
		gpio_pin_configure(col_ports[c], col_pins[c], GPIO_INPUT);
	}
	lcd_init();

	while (1) {
		for (int r = 0; r < 2; ++r) {
			gpio_pin_set_raw(gpio1_dev, row_pins[r], 0);
			k_msleep(1);
			for (int c = 0; c < 3; ++c) {
				bool pressed = gpio_pin_get_raw(col_ports[c], col_pins[c]) == 0;

				if (pressed && !held[r][c] && !unlocked && count < 4) {
					entered[count++] = legend[r][c];
				}
				held[r][c] = pressed;
			}
			gpio_pin_set_raw(gpio1_dev, row_pins[r], 1);
		}
		if (count == 4) {
			bool match = entered[0] == '1' && entered[1] == '2' &&
				     entered[2] == '3' && entered[3] == '4';

			lcd_clear();
			lcd_goto(0, 0);
			snprintf(line, sizeof(line), "Input: %s", entered);
			lcd_print(line);
			lcd_goto(1, 0);
			lcd_print(match ? "Status: Success" : "Status: Fail");
			if (match) {
				unlocked = true;
				gpio_pin_set(gpio0_dev, RELAY_PIN, 1);
			}
			count = 0;
		}
		k_msleep(5);
	}
	return 0;
}
"""


def zephyr_reaction_timer_display(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + zephyr_lcd_driver_block() + """
#define BTN_PIN 11
#define SHOCK_PIN 10

int main(void)
{
	char line[17];

	gpio_pin_configure(gpio1_dev, BTN_PIN, GPIO_INPUT);
	gpio_pin_configure(gpio1_dev, SHOCK_PIN, GPIO_INPUT);
	lcd_init();
	lcd_print("Ready");

	while (gpio_pin_get_raw(gpio1_dev, BTN_PIN) == 0) {
		k_msleep(1);
	}
	int64_t start = k_uptime_get();

	while (gpio_pin_get_raw(gpio1_dev, SHOCK_PIN) == 0) {
		k_msleep(1);
	}
	int64_t elapsed = k_uptime_get() - start;

	lcd_clear();
	lcd_goto(0, 0);
	snprintf(line, sizeof(line), "%lld ms", (long long)elapsed);
	lcd_print(line);
	while (1) {
		k_msleep(1000);
	}
	return 0;
}
"""


def zephyr_water_level_display(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + ZEPHYR_ADC_HEADER + zephyr_lcd_driver_block() + """
int main(void)
{
	int last_bar = -1;

	adc_setup(0, NRF_SAADC_AIN0);
	lcd_init();
	lcd_goto(0, 0);
	lcd_print("Water Level");

	while (1) {
		if (adc_read(adc_dev, &adc_seq) == 0) {
			int bar = (int)adc_sample * 16 / 4096;

			if (adc_sample > 0 && bar == 0) {
				bar = 1;
			}
			if (bar != last_bar) {
				lcd_goto(1, 0);
				for (int i = 0; i < 16; ++i) {
					lcd_write_byte(1, i < bar ? '#' : ' ');
				}
				last_bar = bar;
			}
		}
		k_msleep(50);
	}
	return 0;
}
"""


ZEPHYR_MPU6050_READ_BLOCK = """\
#include <zephyr/drivers/i2c.h>

#define MPU6050_ADDR 0x68

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

static int mpu_read(int16_t accel[3], int16_t gyro[3])
{
	uint8_t raw[14];

	if (i2c_burst_read(i2c_dev, MPU6050_ADDR, 0x3B, raw, sizeof(raw)) != 0) {
		return -1;
	}
	for (int i = 0; i < 3; ++i) {
		accel[i] = (int16_t)((raw[2 * i] << 8) | raw[2 * i + 1]);
		gyro[i] = (int16_t)((raw[8 + 2 * i] << 8) | raw[9 + 2 * i]);
	}
	return 0;
}

static void lcd_show_imu(int ax, int ay, int az, int gx, int gy, int gz)
{
	char line[17];

	lcd_clear();
	lcd_goto(0, 0);
	snprintf(line, sizeof(line), "Accel: %d %d %d", ax, ay, az);
	lcd_print(line);
	lcd_goto(1, 0);
	snprintf(line, sizeof(line), "Gyro: %d %d %d", gx, gy, gz);
	lcd_print(line);
}

"""


def zephyr_mpu6050_button_display(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + zephyr_lcd_driver_block() + ZEPHYR_MPU6050_READ_BLOCK + """
#define BTN_PIN 11

static struct gpio_callback btn_cb;
static volatile int presses;

static void on_press(const struct device *port, struct gpio_callback *cb, uint32_t pins)
{
	presses++;
}

int main(void)
{
	int16_t accel[3], gyro[3];
	int handled = 0;

	(void)i2c_reg_write_byte(i2c_dev, MPU6050_ADDR, 0x6B, 0x00);
	gpio_pin_configure(gpio1_dev, BTN_PIN, GPIO_INPUT);
	gpio_init_callback(&btn_cb, on_press, BIT(BTN_PIN));
	gpio_add_callback(gpio1_dev, &btn_cb);
	gpio_pin_interrupt_configure(gpio1_dev, BTN_PIN, GPIO_INT_EDGE_RISING);
	lcd_init();

	while (1) {
		if (presses != handled) {
			handled = presses;
			if (mpu_read(accel, gyro) == 0) {
				lcd_show_imu(accel[0], accel[1], accel[2],
					     gyro[0], gyro[1], gyro[2]);
			}
		}
		k_msleep(5);
	}
	return 0;
}
"""


def zephyr_mpu6050_periodic_display(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + zephyr_lcd_driver_block() + ZEPHYR_MPU6050_READ_BLOCK + """
#define SAMPLES 10

int main(void)
{
	int16_t accel[3], gyro[3];
	int32_t acc_sum[3] = {0};
	int32_t gyr_sum[3] = {0};
	int count = 0;

	(void)i2c_reg_write_byte(i2c_dev, MPU6050_ADDR, 0x6B, 0x00);
	lcd_init();

	while (1) {
		if (mpu_read(accel, gyro) == 0) {
			for (int i = 0; i < 3; ++i) {
				acc_sum[i] += accel[i];
				gyr_sum[i] += gyro[i];
			}
			count++;
			if (count >= SAMPLES) {
				lcd_show_imu(acc_sum[0] / SAMPLES, acc_sum[1] / SAMPLES,
					     acc_sum[2] / SAMPLES, gyr_sum[0] / SAMPLES,
					     gyr_sum[1] / SAMPLES, gyr_sum[2] / SAMPLES);
				for (int i = 0; i < 3; ++i) {
					acc_sum[i] = 0;
					gyr_sum[i] = 0;
				}
				count = 0;
			}
		}
		k_msleep(100);
	}
	return 0;
}
"""


def zephyr_tmp36_button_display(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + ZEPHYR_ADC_HEADER + zephyr_lcd_driver_block() + """
#define BTN_PIN 11

static struct gpio_callback btn_cb;
static volatile int presses;

static void on_press(const struct device *port, struct gpio_callback *cb, uint32_t pins)
{
	presses++;
}

int main(void)
{
	char line[17];
	int handled = 0;

	adc_setup(0, NRF_SAADC_AIN0);
	gpio_pin_configure(gpio1_dev, BTN_PIN, GPIO_INPUT);
	gpio_init_callback(&btn_cb, on_press, BIT(BTN_PIN));
	gpio_add_callback(gpio1_dev, &btn_cb);
	gpio_pin_interrupt_configure(gpio1_dev, BTN_PIN, GPIO_INT_EDGE_RISING);
	lcd_init();

	while (1) {
		if (presses != handled) {
			handled = presses;
			if (adc_read(adc_dev, &adc_seq) == 0) {
				/* C*10 = (mV - 500); F*10 = C*10 * 9/5 + 320 */
				int mv = (int)adc_sample * 3300 / 4095;
				int f10 = (mv - 500) * 9 / 5 + 320;

				lcd_clear();
				lcd_goto(0, 0);
				snprintf(line, sizeof(line), "Temp: %d.%d F", f10 / 10, f10 % 10);
				lcd_print(line);
			}
		}
		k_msleep(5);
	}
	return 0;
}
"""


def zephyr_tmp36_periodic_display(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + ZEPHYR_ADC_HEADER + zephyr_lcd_driver_block() + """
#define BTN_PIN 11

static struct gpio_callback btn_cb;
static volatile bool reset_requested;

static void on_press(const struct device *port, struct gpio_callback *cb, uint32_t pins)
{
	reset_requested = true;
}

int main(void)
{
	char prev[17] = "";
	char line[17];
	int counter = 0;

	adc_setup(0, NRF_SAADC_AIN0);
	gpio_pin_configure(gpio1_dev, BTN_PIN, GPIO_INPUT);
	gpio_init_callback(&btn_cb, on_press, BIT(BTN_PIN));
	gpio_add_callback(gpio1_dev, &btn_cb);
	gpio_pin_interrupt_configure(gpio1_dev, BTN_PIN, GPIO_INT_EDGE_RISING);
	lcd_init();

	while (1) {
		k_msleep(1000);
		if (reset_requested) {
			reset_requested = false;
			counter = 0;
			prev[0] = '\\0';
			lcd_clear();
		}
		if (adc_read(adc_dev, &adc_seq) == 0) {
			counter++;
			snprintf(line, sizeof(line), "Temp #%d: %d F", counter, (int)adc_sample);
			lcd_clear();
			if (prev[0] != '\\0') {
				lcd_goto(0, 0);
				lcd_print(prev);
				lcd_goto(1, 0);
			} else {
				lcd_goto(1, 0);
			}
			lcd_print(line);
			snprintf(prev, sizeof(prev), "%s", line);
		}
	}
	return 0;
}
"""


def zephyr_joystick_buzzer_pitch(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + ZEPHYR_ADC_HEADER + """
#define BUZZER_PIN 27

int main(void)
{
	int half_us = 1000;

	adc_setup(1, NRF_SAADC_AIN1);
	gpio_pin_configure(gpio0_dev, BUZZER_PIN, GPIO_OUTPUT_LOW);

	while (1) {
		if (adc_read(adc_dev, &adc_seq) == 0) {
			int freq = 100 + (int)adc_sample * 1900 / 4096;

			half_us = (500000 / freq) / 21;
			if (half_us < 1) {
				half_us = 1;
			}
		}
		/* ~20 carrier periods between ADC reads (<70 ms even at 290 Hz) */
		for (int i = 0; i < 20; ++i) {
			gpio_pin_set(gpio0_dev, BUZZER_PIN, 1);
			k_busy_wait(half_us);
			gpio_pin_set(gpio0_dev, BUZZER_PIN, 0);
			k_busy_wait(half_us);
		}
	}
	return 0;
}
"""


def zephyr_breathing_led(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + """
#define LED_PIN 24
#define CARRIER_US 1000
#define STEP_PERIODS 1 /* One Renode-observed software PWM cycle per duty step. */

static void pwm_step(int duty_percent)
{
	int on_us = CARRIER_US * duty_percent / 100;

	for (int i = 0; i < STEP_PERIODS; ++i) {
		if (on_us > 0) {
			gpio_pin_set(gpio0_dev, LED_PIN, 1);
			k_busy_wait(on_us);
		}
		if (on_us < CARRIER_US) {
			gpio_pin_set(gpio0_dev, LED_PIN, 0);
			k_busy_wait(CARRIER_US - on_us);
		}
	}
}

int main(void)
{
	gpio_pin_configure(gpio0_dev, LED_PIN, GPIO_OUTPUT_LOW);
	while (1) {
		for (int level = 1; level <= 50; ++level) {
			pwm_step(level * 2);
		}
		for (int level = 50; level >= 1; --level) {
			pwm_step(level * 2);
		}
	}
	return 0;
}
"""


def zephyr_lcd_auto_brightness(task: TaskConfig) -> str:
    return ZEPHYR_GPIO_HEADER + ZEPHYR_ADC_HEADER + zephyr_lcd_driver_block() + """
#define K_PIN 8
#define CARRIER_US 2000

int main(void)
{
	int duty = 50;

	adc_setup(0, NRF_SAADC_AIN0);
	gpio_pin_configure(gpio1_dev, K_PIN, GPIO_OUTPUT_LOW);
	lcd_init();
	lcd_print("Backlight auto");

	while (1) {
		if (adc_read(adc_dev, &adc_seq) == 0) {
			duty = (int)adc_sample * 100 / 4096;
		}
		/* ~10 carrier periods (20 ms) between ADC reads */
		for (int i = 0; i < 10; ++i) {
			int on_us = CARRIER_US * duty / 100;

			if (on_us > 0) {
				gpio_pin_set(gpio1_dev, K_PIN, 1);
				k_busy_wait(on_us);
			}
			if (on_us < CARRIER_US) {
				gpio_pin_set(gpio1_dev, K_PIN, 0);
				k_busy_wait(CARRIER_US - on_us);
			}
		}
	}
	return 0;
}
"""


def zephyr_safebox(task: TaskConfig) -> str:
    """Two-row keypad scan with edge detection; after each 4 entered keys the
    code is compared against "1234" and the relay latches high on a match."""

    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

#define RELAY_PIN 13

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

static const int row_pins[2] = {11, 12};
static const char legend[2][3] = {{'1', '2', '3'}, {'4', '5', '6'}};

struct line {
\tconst struct device *port;
\tint pin;
};

int main(void)
{
\tconst struct line cols[3] = {
\t\t{gpio1_dev, 14}, {gpio0_dev, 23}, {gpio0_dev, 21},
\t};
\tbool held[2][3] = {0};
\tchar entered[5] = {0};
\tint count = 0;
\tbool unlocked = false;

\tgpio_pin_configure(gpio0_dev, RELAY_PIN, GPIO_OUTPUT_LOW);
\tfor (int r = 0; r < 2; ++r) {
\t\tgpio_pin_configure(gpio1_dev, row_pins[r], GPIO_OUTPUT_HIGH);
\t}
\tfor (int c = 0; c < 3; ++c) {
\t\tgpio_pin_configure(cols[c].port, cols[c].pin, GPIO_INPUT);
\t}

\twhile (1) {
\t\tfor (int r = 0; r < 2; ++r) {
\t\t\tgpio_pin_set_raw(gpio1_dev, row_pins[r], 0);
\t\t\tk_msleep(1);
\t\t\tfor (int c = 0; c < 3; ++c) {
\t\t\t\tbool pressed = gpio_pin_get_raw(cols[c].port, cols[c].pin) == 0;

\t\t\t\tif (pressed && !held[r][c] && !unlocked && count < 4) {
\t\t\t\t\tentered[count++] = legend[r][c];
\t\t\t\t}
\t\t\t\theld[r][c] = pressed;
\t\t\t}
\t\t\tgpio_pin_set_raw(gpio1_dev, row_pins[r], 1);
\t\t}
\t\tif (count == 4) {
\t\t\tif (entered[0] == '1' && entered[1] == '2' &&
\t\t\t    entered[2] == '3' && entered[3] == '4') {
\t\t\t\tunlocked = true;
\t\t\t\tgpio_pin_set(gpio0_dev, RELAY_PIN, 1);
\t\t\t}
\t\t\tcount = 0;
\t\t}
\t\tk_msleep(5);
\t}
\treturn 0;
}
"""


def zephyr_step_counter_print(task: TaskConfig) -> str:
    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define MPU6050_ADDR 0x68
#define PWR_MGMT_1 0x6B
#define ACCEL_ZOUT_H 0x3F
#define STEP_THRESHOLD 23700 /* ~1.45 g at 16384 counts/g */

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

int main(void)
{
\tuint8_t raw[2];
\tint steps = 0;
\tbool above = false;

\t(void)i2c_reg_write_byte(i2c_dev, MPU6050_ADDR, PWR_MGMT_1, 0x00);
\twhile (1) {
\t\tif (i2c_burst_read(i2c_dev, MPU6050_ADDR, ACCEL_ZOUT_H, raw, sizeof(raw)) == 0) {
\t\t\tint16_t az = (int16_t)((raw[0] << 8) | raw[1]);

\t\t\tif (az > STEP_THRESHOLD && !above) {
\t\t\t\tabove = true;
\t\t\t\tprintk("%d\\n", ++steps);
\t\t\t} else if (az <= STEP_THRESHOLD) {
\t\t\t\tabove = false;
\t\t\t}
\t\t}
\t\tk_msleep(40);
\t}
\treturn 0;
}
"""


def zephyr_rotary_encoder(task: TaskConfig) -> str:
    """Quadrature decoder over the Gray-code transition table: quarter steps
    accumulate per transition and commit one detent (+/-1) when the lines
    return to the 11 idle state."""

    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

#define CLK_PIN 11
#define DT_PIN 12

static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

/* quarter-step direction per (previous state, new state), state = CLK<<1|DT */
static const int8_t quarter[4][4] = {
\t/* from 00 */ {0, -1, 1, 0},
\t/* from 01 */ {1, 0, 0, -1},
\t/* from 10 */ {-1, 0, 0, 1},
\t/* from 11 */ {0, 1, -1, 0},
};

int main(void)
{
\tint position = 0;
\tint quarters = 0;

\tgpio_pin_configure(gpio1_dev, CLK_PIN, GPIO_INPUT);
\tgpio_pin_configure(gpio1_dev, DT_PIN, GPIO_INPUT);

\tint prev = (gpio_pin_get_raw(gpio1_dev, CLK_PIN) << 1) | gpio_pin_get_raw(gpio1_dev, DT_PIN);

\twhile (1) {
\t\tint state = (gpio_pin_get_raw(gpio1_dev, CLK_PIN) << 1) |
\t\t\t    gpio_pin_get_raw(gpio1_dev, DT_PIN);

\t\tif (state != prev) {
\t\t\tquarters += quarter[prev][state];
\t\t\tprev = state;
\t\t\tif (state == 3) {
\t\t\t\tif (quarters >= 4) {
\t\t\t\t\tposition++;
\t\t\t\t\tprintk("Position: %d Direction: CW\\n", position);
\t\t\t\t} else if (quarters <= -4) {
\t\t\t\t\tposition--;
\t\t\t\t\tprintk("Position: %d Direction: CCW\\n", position);
\t\t\t\t}
\t\t\t\tquarters = 0;
\t\t\t}
\t\t}
\t\tk_msleep(1);
\t}
\treturn 0;
}
"""


def zephyr_mpu6050_read_i2c(task: TaskConfig) -> str:
    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define MPU6050_ADDR 0x68
#define PWR_MGMT_1 0x6B
#define ACCEL_XOUT_H 0x3B

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

int main(void)
{
\tuint8_t raw[14];

\t/* Wake from sleep: clear the SLEEP bit (power-on default 0x40). */
\t(void)i2c_reg_write_byte(i2c_dev, MPU6050_ADDR, PWR_MGMT_1, 0x00);

\twhile (1) {
\t\tif (i2c_burst_read(i2c_dev, MPU6050_ADDR, ACCEL_XOUT_H, raw, sizeof(raw)) == 0) {
\t\t\tint16_t ax = (int16_t)((raw[0] << 8) | raw[1]);
\t\t\tint16_t ay = (int16_t)((raw[2] << 8) | raw[3]);
\t\t\tint16_t az = (int16_t)((raw[4] << 8) | raw[5]);
\t\t\tint16_t gx = (int16_t)((raw[8] << 8) | raw[9]);
\t\t\tint16_t gy = (int16_t)((raw[10] << 8) | raw[11]);
\t\t\tint16_t gz = (int16_t)((raw[12] << 8) | raw[13]);

\t\t\tprintk("Accel: %d %d %d Gyro: %d %d %d\\n", ax, ay, az, gx, gy, gz);
\t\t}
\t\tk_msleep(150);
\t}
\treturn 0;
}
"""


def zephyr_bme280_read_i2c(task: TaskConfig) -> str:
    """Register-level BME280 driver: calibration read, mode config, raw data
    read, and the Bosch datasheet integer compensation for temperature and
    humidity (pressure is excluded from the Renode oracle; see the task YAML).
    printk has no float support in the harness prj.conf, so decimals are
    formatted from integer math."""

    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define BME280_ADDR 0x76

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

/* Separate stopped write+read transactions: the simulated bus does not
 * support repeated-start combined transfers (stated in the prompt). */
static int bme_read(uint8_t reg, uint8_t *buf, uint32_t len)
{
	if (i2c_write(i2c_dev, &reg, 1, BME280_ADDR) != 0) {
		return -1;
	}
	return i2c_read(i2c_dev, buf, len, BME280_ADDR);
}

static uint16_t dig_t1;
static int16_t dig_t2, dig_t3;
static uint8_t dig_h1, dig_h3;
static int16_t dig_h2, dig_h4, dig_h5;
static int8_t dig_h6;
static int32_t t_fine;

static int read_calibration(void)
{
\tuint8_t buf[26];

\tif (bme_read(0x88, buf, 26) != 0) {
\t\treturn -1;
\t}
\tdig_t1 = (uint16_t)((buf[1] << 8) | buf[0]);
\tdig_t2 = (int16_t)((buf[3] << 8) | buf[2]);
\tdig_t3 = (int16_t)((buf[5] << 8) | buf[4]);
\tdig_h1 = buf[25];
\tif (bme_read(0xE1, buf, 7) != 0) {
\t\treturn -1;
\t}
\tdig_h2 = (int16_t)((buf[1] << 8) | buf[0]);
\tdig_h3 = buf[2];
\tdig_h4 = (int16_t)((buf[3] << 4) | (buf[4] & 0x0F));
\tdig_h5 = (int16_t)((buf[5] << 4) | (buf[4] >> 4));
\tdig_h6 = (int8_t)buf[6];
\treturn 0;
}

static int32_t compensate_temperature(int32_t adc_t)
{
\tint32_t var1 = ((((adc_t >> 3) - ((int32_t)dig_t1 << 1))) * (int32_t)dig_t2) >> 11;
\tint32_t var2 = (((((adc_t >> 4) - (int32_t)dig_t1) *
\t\t\t  ((adc_t >> 4) - (int32_t)dig_t1)) >> 12) * (int32_t)dig_t3) >> 14;

\tt_fine = var1 + var2;
\treturn (t_fine * 5 + 128) >> 8; /* 0.01 degC */
}

static uint32_t compensate_humidity(int32_t adc_h)
{
\tint32_t v = t_fine - 76800;

\tv = ((((adc_h << 14) - ((int32_t)dig_h4 << 20) - ((int32_t)dig_h5 * v)) + 16384) >> 15) *
\t    (((((((v * (int32_t)dig_h6) >> 10) *
\t\t (((v * (int32_t)dig_h3) >> 11) + 32768)) >> 10) + 2097152) *
\t\t  (int32_t)dig_h2 + 8192) >> 14);
\tv = v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)dig_h1) >> 4);
\tv = v < 0 ? 0 : v;
\tv = v > 419430400 ? 419430400 : v;
\treturn (uint32_t)(v >> 12); /* %RH in Q22.10 */
}

int main(void)
{
\tuint8_t raw[8];

\tif (read_calibration() != 0) {
\t\tprintk("BME280 calibration read failed\\n");
\t\treturn 0;
\t}
\t/* humidity oversampling x1, then temp/press oversampling x1, normal mode */
\t(void)i2c_reg_write_byte(i2c_dev, BME280_ADDR, 0xF2, 0x01);
\t(void)i2c_reg_write_byte(i2c_dev, BME280_ADDR, 0xF4, 0x27);

\twhile (1) {
\t\tif (bme_read(0xF7, raw, sizeof(raw)) == 0) {
\t\t\tint32_t adc_t = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) | (raw[5] >> 4);
\t\t\tint32_t adc_h = ((int32_t)raw[6] << 8) | raw[7];
\t\t\tint32_t temp = compensate_temperature(adc_t);
\t\t\tuint32_t hum = compensate_humidity(adc_h);
\t\t\tint32_t t_whole = temp / 100;
\t\t\tint32_t t_frac = temp % 100;
\t\t\tuint32_t h_deci = (hum * 10) >> 10;

\t\t\tif (t_frac < 0) {
\t\t\t\tt_frac = -t_frac;
\t\t\t}
\t\t\tprintk("Temperature: %d.%02d C Humidity: %u.%u %%\\n",
\t\t\t       t_whole, t_frac, h_deci / 10, h_deci % 10);
\t\t}
\t\tk_msleep(200);
\t}
\treturn 0;
}
"""


ZEPHYR_DHT11_BLOCK = """\
static const struct gpio_dt_spec dht = GPIO_DT_SPEC_GET(DT_ALIAS(data_dht11), gpios);

static int wait_level(int level, uint32_t timeout_us)
{
\tuint32_t start = k_cycle_get_32();
\tuint32_t timeout = k_us_to_cyc_ceil32(timeout_us);

\twhile (gpio_pin_get_dt(&dht) != level) {
\t\tif ((uint32_t)(k_cycle_get_32() - start) > timeout) {
\t\t\treturn -1;
\t\t}
\t}
\treturn 0;
}

static int dht11_read(int *temperature, int *humidity)
{
\tuint8_t data[5] = {0};

\tgpio_pin_configure_dt(&dht, GPIO_OUTPUT_HIGH);
\tk_busy_wait(50);
\tgpio_pin_set_dt(&dht, 0);
\tk_msleep(20);
\tgpio_pin_configure_dt(&dht, GPIO_INPUT | GPIO_PULL_UP);

\tif (wait_level(0, 3000) != 0 || wait_level(1, 3000) != 0 || wait_level(0, 3000) != 0) {
\t\treturn -1;
\t}
\tfor (int bit = 0; bit < 40; ++bit) {
\t\tuint32_t high_start, high_us;

\t\tif (wait_level(1, 3000) != 0) {
\t\t\treturn -1;
\t\t}
\t\thigh_start = k_cycle_get_32();
\t\tif (wait_level(0, 3000) != 0) {
\t\t\treturn -1;
\t\t}
\t\thigh_us = k_cyc_to_us_floor32(k_cycle_get_32() - high_start);
\t\tdata[bit / 8] <<= 1;
\t\tif (high_us > 1000) {
\t\t\tdata[bit / 8] |= 1;
\t\t}
\t}
\tif (((data[0] + data[1] + data[2] + data[3]) & 0xFF) != data[4]) {
\t\treturn -2;
\t}
\t*humidity = data[0];
\t*temperature = data[2];
\treturn 0;
}
"""


def zephyr_dht11_read(task: TaskConfig) -> str:
    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

""" + ZEPHYR_DHT11_BLOCK + """
int main(void)
{
\twhile (1) {
\t\tint temperature = 0;
\t\tint humidity = 0;
\t\tint rc = dht11_read(&temperature, &humidity);

\t\tif (rc == 0) {
\t\t\tprintk("Temperature: %d C Humidity: %d %%\\n", temperature, humidity);
\t\t} else {
\t\t\tprintk("DHT11 checksum/read error\\n");
\t\t}
\t\tk_msleep(800);
\t}
\treturn 0;
}
"""


def zephyr_dht11_button_display(task: TaskConfig) -> str:
    pins = task.fixture.get("components", [])[2].get("pins", {})
    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <stdio.h>

static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(DT_ALIAS(my_button), gpios);
static struct gpio_callback button_cb;
static volatile bool requested;
static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

""" + ZEPHYR_DHT11_BLOCK + zephyr_lcd_driver_block(pins) + """
static void on_button(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
\tARG_UNUSED(dev);
\tARG_UNUSED(cb);
\tARG_UNUSED(pins);
\trequested = true;
}

static void show_reading(void)
{
\tint temperature = 0;
\tint humidity = 0;
\tchar line[17];

\tif (dht11_read(&temperature, &humidity) != 0) {
\t\tlcd_clear();
\t\tlcd_print("DHT11 error");
\t\treturn;
\t}
\tlcd_clear();
\tlcd_goto(0, 0);
\tsnprintf(line, sizeof(line), "Temp: %d.0 C", temperature);
\tlcd_print(line);
\tlcd_goto(1, 0);
\tsnprintf(line, sizeof(line), "RH: %d.0 %%", humidity);
\tlcd_print(line);
}

int main(void)
{
\tgpio_pin_configure_dt(&button, GPIO_INPUT | GPIO_PULL_UP);
\tgpio_pin_interrupt_configure_dt(&button, GPIO_INT_EDGE_TO_ACTIVE);
\tgpio_init_callback(&button_cb, on_button, BIT(button.pin));
\tgpio_add_callback(button.port, &button_cb);
\tlcd_init();
\trequested = true;
\twhile (1) {
\t\tif (requested) {
\t\t\trequested = false;
\t\t\tshow_reading();
\t\t}
\t\tk_msleep(20);
\t}
\treturn 0;
}
"""


ZEPHYR_DS18B20_BLOCK = """\
static const struct gpio_dt_spec ds = GPIO_DT_SPEC_GET(DT_ALIAS(data_ds18b20), gpios);

/* Renode's GPIO connections are unidirectional, so the open-drain bus release
 * is invisible to the slave model. Drive the line push-pull during the reset
 * and write phases (so the model observes the master's edges and low-pulse
 * widths) and only release it during a read slot so the model can answer. The
 * bit windows are a deliberate ~10x stretch of the real DS18B20 timing so the
 * simulator's ~30 us RTC resolution can resolve them; the task prompt
 * documents the scale a submission must target. */
static void ow_low(void)
{
\tgpio_pin_configure_dt(&ds, GPIO_OUTPUT_LOW);
}

static void ow_high(void)
{
\tgpio_pin_configure_dt(&ds, GPIO_OUTPUT_HIGH);
}

static void ow_release(void)
{
\tgpio_pin_configure_dt(&ds, GPIO_INPUT | GPIO_PULL_UP);
}

static int ow_reset(void)
{
\tint presence;

\tow_low();
\tk_busy_wait(2000);
\tow_high();
\tow_release();
\tk_busy_wait(90);
\tpresence = gpio_pin_get_dt(&ds) == 0;
\tk_busy_wait(600);
\tow_high();
\treturn presence ? 0 : -1;
}

static void ow_write_bit(int bit)
{
\tow_low();
\tif (bit) {
\t\tk_busy_wait(30);
\t\tow_high();
\t\tk_busy_wait(400);
\t} else {
\t\tk_busy_wait(400);
\t\tow_high();
\t\tk_busy_wait(30);
\t}
}

static int ow_read_bit(void)
{
\tint bit;

\tow_low();
\tk_busy_wait(60);
\tow_release();
\tk_busy_wait(120);
\tbit = gpio_pin_get_dt(&ds);
\tk_busy_wait(300);
\tow_high();
\treturn bit;
}

static void ow_write_byte(uint8_t value)
{
\tfor (int i = 0; i < 8; ++i) {
\t\tow_write_bit((value >> i) & 1);
\t}
}

static uint8_t ow_read_byte(void)
{
\tuint8_t value = 0;

\tfor (int i = 0; i < 8; ++i) {
\t\tvalue |= ow_read_bit() << i;
\t}
\treturn value;
}

static uint8_t ow_crc8(const uint8_t *data, int count)
{
\tuint8_t crc = 0;

\tfor (int i = 0; i < count; ++i) {
\t\tuint8_t in = data[i];
\t\tfor (int bit = 0; bit < 8; ++bit) {
\t\t\tuint8_t mix = (crc ^ in) & 1;
\t\t\tcrc >>= 1;
\t\t\tif (mix) {
\t\t\t\tcrc ^= 0x8C;
\t\t\t}
\t\t\tin >>= 1;
\t\t}
\t}
\treturn crc;
}

static int ds18b20_read_c_x16(int *temp_x16)
{
\tuint8_t scratch[9];

\tif (ow_reset() != 0) {
\t\treturn -1;
\t}
\tow_write_byte(0xCC);
\tow_write_byte(0x44);
\tk_msleep(100);
\tif (ow_reset() != 0) {
\t\treturn -1;
\t}
\tow_write_byte(0xCC);
\tow_write_byte(0xBE);
\tfor (int i = 0; i < 9; ++i) {
\t\tscratch[i] = ow_read_byte();
\t}
\tif (ow_crc8(scratch, 8) != scratch[8]) {
\t\treturn -2;
\t}
\t*temp_x16 = (int16_t)((scratch[1] << 8) | scratch[0]);
\treturn 0;
}
"""


def zephyr_ds18b20_heat_alarm(task: TaskConfig) -> str:
    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(my_led), gpios);
static const struct gpio_dt_spec buzzer = GPIO_DT_SPEC_GET(DT_ALIAS(my_buzzer), gpios);

""" + ZEPHYR_DS18B20_BLOCK + """
int main(void)
{
\tgpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
\tgpio_pin_configure_dt(&buzzer, GPIO_OUTPUT_INACTIVE);
\twhile (1) {
\t\tint temp_x16 = 0;
\t\tif (ds18b20_read_c_x16(&temp_x16) == 0 && temp_x16 > 30 * 16) {
\t\t\tgpio_pin_set_dt(&buzzer, 1);
\t\t\tgpio_pin_toggle_dt(&led);
\t\t\tk_msleep(80);
\t\t} else {
\t\t\tgpio_pin_set_dt(&buzzer, 0);
\t\t\tgpio_pin_set_dt(&led, 0);
\t\t\tk_msleep(80);
\t\t}
\t}
\treturn 0;
}
"""


def zephyr_bme280_read_spi(task: TaskConfig) -> str:
    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/sys/printk.h>
#include <string.h>

static const struct spi_dt_spec bme =
\tSPI_DT_SPEC_GET(DT_ALIAS(my_sensor), SPI_OP_MODE_MASTER | SPI_WORD_SET(8) | SPI_TRANSFER_MSB, 0);

static int bme_read(uint8_t reg, uint8_t *buf, size_t len)
{
\tuint8_t tx[32] = {0};
\tuint8_t rx[32] = {0};
\tconst struct spi_buf tx_buf = {.buf = tx, .len = len + 1};
\tconst struct spi_buf rx_buf = {.buf = rx, .len = len + 1};
\tconst struct spi_buf_set tx_set = {.buffers = &tx_buf, .count = 1};
\tconst struct spi_buf_set rx_set = {.buffers = &rx_buf, .count = 1};

\tif (len + 1 > sizeof(tx)) {
\t\treturn -1;
\t}
\ttx[0] = reg | 0x80;
\tint err = spi_transceive_dt(&bme, &tx_set, &rx_set);
\tif (err != 0) {
\t\treturn err;
\t}
\tmemcpy(buf, &rx[1], len);
\treturn 0;
}

static int bme_write(uint8_t reg, uint8_t value)
{
\tuint8_t tx[2] = {reg & 0x7F, value};
\tconst struct spi_buf tx_buf = {.buf = tx, .len = sizeof(tx)};
\tconst struct spi_buf_set tx_set = {.buffers = &tx_buf, .count = 1};

\treturn spi_write_dt(&bme, &tx_set);
}

static uint16_t dig_t1;
static int16_t dig_t2, dig_t3;
static uint8_t dig_h1, dig_h3;
static int16_t dig_h2, dig_h4, dig_h5;
static int8_t dig_h6;
static int32_t t_fine;

static int read_calibration(void)
{
\tuint8_t buf[26];
\tint err;

\terr = bme_read(0x88, buf, 26);
\tif (err != 0) {
\t\treturn err;
\t}
\tdig_t1 = (uint16_t)((buf[1] << 8) | buf[0]);
\tdig_t2 = (int16_t)((buf[3] << 8) | buf[2]);
\tdig_t3 = (int16_t)((buf[5] << 8) | buf[4]);
\tdig_h1 = buf[25];
\terr = bme_read(0xE1, buf, 7);
\tif (err != 0) {
\t\treturn err;
\t}
\tdig_h2 = (int16_t)((buf[1] << 8) | buf[0]);
\tdig_h3 = buf[2];
\tdig_h4 = (int16_t)((buf[3] << 4) | (buf[4] & 0x0F));
\tdig_h5 = (int16_t)((buf[5] << 4) | (buf[4] >> 4));
\tdig_h6 = (int8_t)buf[6];
\treturn 0;
}

static int32_t compensate_temperature(int32_t adc_t)
{
\tint32_t var1 = ((((adc_t >> 3) - ((int32_t)dig_t1 << 1))) * (int32_t)dig_t2) >> 11;
\tint32_t var2 = (((((adc_t >> 4) - (int32_t)dig_t1) *
\t\t\t  ((adc_t >> 4) - (int32_t)dig_t1)) >> 12) * (int32_t)dig_t3) >> 14;

\tt_fine = var1 + var2;
\treturn (t_fine * 5 + 128) >> 8;
}

static uint32_t compensate_humidity(int32_t adc_h)
{
\tint32_t v = t_fine - 76800;

\tv = ((((adc_h << 14) - ((int32_t)dig_h4 << 20) - ((int32_t)dig_h5 * v)) + 16384) >> 15) *
\t    (((((((v * (int32_t)dig_h6) >> 10) *
\t\t (((v * (int32_t)dig_h3) >> 11) + 32768)) >> 10) + 2097152) *
\t\t  (int32_t)dig_h2 + 8192) >> 14);
\tv = v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)dig_h1) >> 4);
\tv = v < 0 ? 0 : v;
\tv = v > 419430400 ? 419430400 : v;
\treturn (uint32_t)(v >> 12);
}

int main(void)
{
\tuint8_t raw[8];
\tint err;

\tif (!spi_is_ready_dt(&bme)) {
\t\tprintk("BME280 SPI not ready\\n");
\t\treturn 0;
\t}
\terr = read_calibration();
\tif (err != 0) {
\t\tprintk("BME280 SPI not found: %d\\n", err);
\t\treturn 0;
\t}
\t(void)bme_write(0xF2, 0x01);
\t(void)bme_write(0xF4, 0x27);
\twhile (1) {
\t\tif (bme_read(0xF7, raw, sizeof(raw)) == 0) {
\t\t\tint32_t adc_t = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) | (raw[5] >> 4);
\t\t\tint32_t adc_h = ((int32_t)raw[6] << 8) | raw[7];
\t\t\tint32_t temp = compensate_temperature(adc_t);
\t\t\tuint32_t hum = compensate_humidity(adc_h);
\t\t\tint32_t t_frac = temp % 100;
\t\t\tuint32_t h_deci = (hum * 10) >> 10;
\t\t\tif (t_frac < 0) {
\t\t\t\tt_frac = -t_frac;
\t\t\t}
\t\t\tprintk("Temperature: %d.%02d C Humidity: %u.%u %%\\n",
\t\t\t       temp / 100, t_frac, h_deci / 10, h_deci % 10);
\t\t}
\t\tk_msleep(250);
\t}
\treturn 0;
}
"""


def zephyr_ds1307_rtc(task: TaskConfig) -> str:
    return """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define DS1307_ADDR 0x68

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

static int from_bcd(uint8_t value)
{
\treturn ((value >> 4) * 10) + (value & 0x0F);
}

int main(void)
{
\tuint8_t reg = 0x00;
\tuint8_t data[7];

\twhile (1) {
\t\tif (i2c_write_read(i2c_dev, DS1307_ADDR, &reg, 1, data, sizeof(data)) == 0) {
\t\t\tprintk("20%02d/%02d/%02d %02d:%02d:%02d\\n",
\t\t\t       from_bcd(data[6]), from_bcd(data[5]), from_bcd(data[4]),
\t\t\t       from_bcd(data[2] & 0x3F), from_bcd(data[1]),
\t\t\t       from_bcd(data[0] & 0x7F));
\t\t}
\t\tk_msleep(250);
\t}
\treturn 0;
}
"""


ZEPHYR_COMMON_INCLUDES = """\
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

"""


def zephyr_port_decl(name: str, port: str) -> str:
    return f"static const struct device *const {name} = DEVICE_DT_GET(DT_NODELABEL({port}));"


def zephyr_blink_1hz(task: TaskConfig) -> str:
    port, index = zephyr_gpio_parts(fixture_pin(task, "led"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("led_port", port)}

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


def zephyr_blink_no_delay(task: TaskConfig) -> str:
    port, index = zephyr_gpio_parts(fixture_pin(task, "led"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("led_port", port)}

int main(void)
{{
\tint level = 0;
\tint64_t last_toggle_ms;

\tgpio_pin_configure(led_port, {index}, GPIO_OUTPUT_LOW);
\tlast_toggle_ms = k_uptime_get();
\twhile (1) {{
\t\tint64_t now = k_uptime_get();

\t\tif (now - last_toggle_ms >= 500) {{
\t\t\tlast_toggle_ms += 500;
\t\t\tlevel = !level;
\t\t\tgpio_pin_set(led_port, {index}, level);
\t\t}}
\t\tk_yield();
\t}}
\treturn 0;
}}
"""


def zephyr_morse_sos(task: TaskConfig) -> str:
    port, index = zephyr_gpio_parts(fixture_pin(task, "led"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("led_port", port)}

static void set_led_for_units(int level, int units)
{{
\tgpio_pin_set(led_port, {index}, level);
\tk_msleep(200 * units);
}}

int main(void)
{{
\tconst int pattern[] = {{1, 1, 1, 3, 3, 3, 1, 1, 1}};

\tgpio_pin_configure(led_port, {index}, GPIO_OUTPUT_LOW);
\twhile (1) {{
\t\tfor (int i = 0; i < 9; ++i) {{
\t\t\tset_led_for_units(1, pattern[i]);
\t\t\tif (i < 8) {{
\t\t\t\tset_led_for_units(0, (i == 2 || i == 5) ? 3 : 1);
\t\t\t}}
\t\t}}
\t\tset_led_for_units(0, 7);
\t}}
\treturn 0;
}}
"""


def zephyr_blink_two_leds(task: TaskConfig) -> str:
    pins = task.fixture.get("pins", {}) if isinstance(task.fixture, dict) else {}
    led1_port, led1_index = zephyr_gpio_parts(str(pins.get("led1", task.board_profile.default_pins["led"])))
    led2_port, led2_index = zephyr_gpio_parts(str(pins.get("led2", task.board_profile.default_pins["led2"])))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("led1_port", led1_port)}
{zephyr_port_decl("led2_port", led2_port)}

int main(void)
{{
\tint led1 = 0;
\tint led2 = 0;
\tint64_t last_led1_ms;
\tint64_t last_led2_ms;

\tgpio_pin_configure(led1_port, {led1_index}, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(led2_port, {led2_index}, GPIO_OUTPUT_LOW);
\tlast_led1_ms = k_uptime_get();
\tlast_led2_ms = last_led1_ms;
\twhile (1) {{
\t\tint64_t now = k_uptime_get();

\t\tif (now - last_led1_ms >= 500) {{
\t\t\tlast_led1_ms += 500;
\t\t\tled1 = !led1;
\t\t\tgpio_pin_set(led1_port, {led1_index}, led1);
\t\t}}
\t\tif (now - last_led2_ms >= 250) {{
\t\t\tlast_led2_ms += 250;
\t\t\tled2 = !led2;
\t\t\tgpio_pin_set(led2_port, {led2_index}, led2);
\t\t}}
\t\tk_yield();
\t}}
\treturn 0;
}}
"""


def zephyr_button_status_display(task: TaskConfig) -> str:
    port, index = zephyr_gpio_parts(fixture_pin(task, "button"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("button_port", port)}

int main(void)
{{
\tint was_pressed = 0;

\tgpio_pin_configure(button_port, {index}, GPIO_INPUT);
\twhile (1) {{
\t\tint pressed = gpio_pin_get(button_port, {index});

\t\tif (pressed && !was_pressed) {{
\t\t\tprintk("Button Pressed!\\n");
\t\t}}
\t\twas_pressed = pressed;
\t\tk_msleep(5);
\t}}
\treturn 0;
}}
"""


def zephyr_buzzer_doorbell(task: TaskConfig) -> str:
    button_port, button_index = zephyr_gpio_parts(fixture_pin(task, "button"))
    buzzer_port, buzzer_index = zephyr_gpio_parts(fixture_pin(task, "buzzer"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("button_port", button_port)}
{zephyr_port_decl("buzzer_port", buzzer_port)}

int main(void)
{{
\tgpio_pin_configure(button_port, {button_index}, GPIO_INPUT);
\tgpio_pin_configure(buzzer_port, {buzzer_index}, GPIO_OUTPUT_LOW);
\twhile (1) {{
\t\tgpio_pin_set(buzzer_port, {buzzer_index}, gpio_pin_get(button_port, {button_index}));
\t\tk_msleep(1);
\t}}
\treturn 0;
}}
"""


def zephyr_buzzer_button(task: TaskConfig) -> str:
    button_port, button_index = zephyr_gpio_parts(fixture_pin(task, "button"))
    buzzer_port, buzzer_index = zephyr_gpio_parts(fixture_pin(task, "buzzer"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("button_port", button_port)}
{zephyr_port_decl("buzzer_port", buzzer_port)}

#define DEBOUNCE_MS 30

int main(void)
{{
\tint stable = 0;
\tint last_reading = 0;
\tint64_t changed_at_ms;

\tgpio_pin_configure(button_port, {button_index}, GPIO_INPUT);
\tgpio_pin_configure(buzzer_port, {buzzer_index}, GPIO_OUTPUT_LOW);
\tchanged_at_ms = k_uptime_get();
\twhile (1) {{
\t\tint reading = gpio_pin_get(button_port, {button_index});
\t\tint64_t now = k_uptime_get();

\t\tif (reading != last_reading) {{
\t\t\tlast_reading = reading;
\t\t\tchanged_at_ms = now;
\t\t}}
\t\tif (now - changed_at_ms >= DEBOUNCE_MS && stable != reading) {{
\t\t\tstable = reading;
\t\t}}
\t\tgpio_pin_set(buzzer_port, {buzzer_index}, stable);
\t\tk_msleep(1);
\t}}
\treturn 0;
}}
"""
def zephyr_digital_follow(task: TaskConfig) -> str:
    input_id = "tilt1" if task.task_id == "tilt_detection_alarm" else "pir1"
    input_default = "button" if task.task_id == "tilt_detection_alarm" else "pir"
    input_port, input_index = zephyr_gpio_parts(zephyr_component_pin(task, input_id, input_default))
    output_port, output_index = zephyr_gpio_parts(zephyr_component_pin(task, "buzzer1", "buzzer"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("input_port", input_port)}
{zephyr_port_decl("output_port", output_port)}

int main(void)
{{
\tgpio_pin_configure(input_port, {input_index}, GPIO_INPUT);
\tgpio_pin_configure(output_port, {output_index}, GPIO_OUTPUT_LOW);

\twhile (1) {{
\t\tgpio_pin_set(output_port, {output_index}, gpio_pin_get(input_port, {input_index}));
\t\tk_msleep(5);
\t}}
\treturn 0;
}}
"""


def zephyr_clap_switch(task: TaskConfig) -> str:
    input_port, input_index = zephyr_gpio_parts(zephyr_component_pin(task, "sound1", "button"))
    output_port, output_index = zephyr_gpio_parts(zephyr_component_pin(task, "relay1", "led"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("input_port", input_port)}
{zephyr_port_decl("relay_port", output_port)}

int main(void)
{{
\tint last = 0;
\tint relay = 0;

\tgpio_pin_configure(input_port, {input_index}, GPIO_INPUT);
\tgpio_pin_configure(relay_port, {output_index}, GPIO_OUTPUT_LOW);

\twhile (1) {{
\t\tint current = gpio_pin_get(input_port, {input_index});
\t\tif (current && !last) {{
\t\t\trelay = !relay;
\t\t\tgpio_pin_set(relay_port, {output_index}, relay);
\t\t}}
\t\tlast = current;
\t\tk_msleep(5);
\t}}
\treturn 0;
}}
"""


def zephyr_buzzer_toggle_led_freq(task: TaskConfig) -> str:
    button_port, button_index = zephyr_gpio_parts(zephyr_component_pin(task, "btn1", "button"))
    led_port, led_index = zephyr_gpio_parts(zephyr_component_pin(task, "led1", "led"))
    buzzer_port, buzzer_index = zephyr_gpio_parts(zephyr_component_pin(task, "buzzer1", "buzzer"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("button_port", button_port)}
{zephyr_port_decl("led_port", led_port)}
{zephyr_port_decl("buzzer_port", buzzer_port)}

static int64_t half_period_ms(int mode)
{{
\tswitch (mode) {{
\tcase 1:
\t\treturn 500;
\tcase 2:
\t\treturn 250;
\tcase 3:
\t\treturn 125;
\tdefault:
\t\treturn 0;
\t}}
}}

int main(void)
{{
\tint mode = 0;
\tint last_button = 0;
\tint led_state = 0;
\tint buzzer_state = 0;
\tint64_t last_led_toggle = k_uptime_get();
\tint64_t last_buzzer_toggle = 0;
\tint64_t buzzer_until = 0;

\tgpio_pin_configure(button_port, {button_index}, GPIO_INPUT);
\tgpio_pin_configure(led_port, {led_index}, GPIO_OUTPUT_LOW);
\tgpio_pin_configure(buzzer_port, {buzzer_index}, GPIO_OUTPUT_LOW);

\twhile (1) {{
\t\tint64_t now = k_uptime_get();
\t\tint button = gpio_pin_get(button_port, {button_index});

\t\tif (button && !last_button) {{
\t\t\tmode = (mode + 1) % 4;
\t\t\tled_state = 0;
\t\t\tlast_led_toggle = now;
\t\t\tgpio_pin_set(led_port, {led_index}, led_state);
\t\t\tbuzzer_until = now + 80;
\t\t\tlast_buzzer_toggle = now;
\t\t}}
\t\tlast_button = button;

\t\tint64_t half = half_period_ms(mode);
\t\tif (half == 0) {{
\t\t\tled_state = 0;
\t\t\tgpio_pin_set(led_port, {led_index}, 0);
\t\t}} else if (now - last_led_toggle >= half) {{
\t\t\tlast_led_toggle += half;
\t\t\tled_state = !led_state;
\t\t\tgpio_pin_set(led_port, {led_index}, led_state);
\t\t}}

\t\tif (now < buzzer_until) {{
\t\t\tif (now - last_buzzer_toggle >= 1) {{
\t\t\t\tlast_buzzer_toggle = now;
\t\t\t\tbuzzer_state = !buzzer_state;
\t\t\t\tgpio_pin_set(buzzer_port, {buzzer_index}, buzzer_state);
\t\t\t}}
\t\t}} else if (buzzer_state) {{
\t\t\tbuzzer_state = 0;
\t\t\tgpio_pin_set(buzzer_port, {buzzer_index}, 0);
\t\t}}

\t\tk_msleep(1);
\t}}
\treturn 0;
}}
"""


def zephyr_button_status_count(task: TaskConfig) -> str:
    port, index = zephyr_gpio_parts(fixture_pin(task, "button"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("button_port", port)}

int main(void)
{{
\tint was_pressed = 0;
\tint count = 0;

\tgpio_pin_configure(button_port, {index}, GPIO_INPUT);
\twhile (1) {{
\t\tint pressed = gpio_pin_get(button_port, {index});

\t\tif (pressed && !was_pressed) {{
\t\t\t++count;
\t\t\tprintk("%d\\n", count);
\t\t}}
\t\twas_pressed = pressed;
\t\tk_msleep(5);
\t}}
\treturn 0;
}}
"""


def zephyr_button_press_debounce(task: TaskConfig) -> str:
    port, index = zephyr_gpio_parts(fixture_pin(task, "button"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("button_port", port)}

#define DEBOUNCE_MS 30

int main(void)
{{
\tint stable = 0;
\tint last_reading = 0;
\tint64_t changed_at_ms;

\tgpio_pin_configure(button_port, {index}, GPIO_INPUT);
\tchanged_at_ms = k_uptime_get();
\twhile (1) {{
\t\tint reading = gpio_pin_get(button_port, {index});
\t\tint64_t now = k_uptime_get();

\t\tif (reading != last_reading) {{
\t\t\tlast_reading = reading;
\t\t\tchanged_at_ms = now;
\t\t}}
\t\tif (now - changed_at_ms >= DEBOUNCE_MS && stable != reading) {{
\t\t\tstable = reading;
\t\t\tif (stable) {{
\t\t\t\tprintk("Button Pressed!\\n");
\t\t\t}}
\t\t}}
\t\tk_msleep(1);
\t}}
\treturn 0;
}}
"""


def zephyr_pir_serial(task: TaskConfig) -> str:
    port, index = zephyr_gpio_parts(fixture_pin(task, "pir"))
    return ZEPHYR_COMMON_INCLUDES + f"""\
{zephyr_port_decl("pir_port", port)}

int main(void)
{{
\tint last_state = -1;

\tgpio_pin_configure(pir_port, {index}, GPIO_INPUT);
\twhile (1) {{
\t\tint state = gpio_pin_get(pir_port, {index});

\t\tif (state != last_state) {{
\t\t\tprintk("%s\\n", state ? "Motion Detected!" : "No Motion Detected!");
\t\t\tlast_state = state;
\t\t}}
\t\tk_msleep(10);
\t}}
\treturn 0;
}}
"""


def zephyr_tmp36_read(task: TaskConfig) -> str:
    profile = task.board_profile
    return f"""\
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/dt-bindings/adc/nrf-saadc.h>
#include <zephyr/sys/printk.h>

static const struct device *const adc_dev = DEVICE_DT_GET(DT_NODELABEL(adc));

int main(void)
{{
\tint16_t sample;
\tstruct adc_channel_cfg channel_cfg = {{
\t\t.gain = ADC_GAIN_1,
\t\t.reference = ADC_REF_INTERNAL,
\t\t.acquisition_time = ADC_ACQ_TIME_DEFAULT,
\t\t.channel_id = 0,
\t\t.input_positive = NRF_SAADC_AIN0,
\t}};
\tstruct adc_sequence sequence = {{
\t\t.channels = BIT(0),
\t\t.buffer = &sample,
\t\t.buffer_size = sizeof(sample),
\t\t.resolution = 12,
\t}};

\tadc_channel_setup(adc_dev, &channel_cfg);
\twhile (1) {{
\t\tif (adc_read(adc_dev, &sequence) == 0) {{
\t\t\tfloat voltage = sample * ({profile.voltage:.6g}f / {float(profile.adc_max):.1f}f);
\t\t\tfloat celsius = (voltage - 0.5f) * 100.0f;
\t\t\tprintk("%.1f\\n", (double)celsius);
\t\t}}
\t\tk_msleep(100);
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
        "mpu6050_read_spi": espidf_mpu6050_spi_serial,
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
    boolean: bool = False,
) -> str:
    includes = [
        "#include <stdio.h>",
        "#include <stdint.h>",
        "#include \"driver/gpio.h\"",
        "#include \"esp_timer.h\"",
        "#include \"freertos/FreeRTOS.h\"",
        "#include \"freertos/task.h\"",
    ]
    if boolean:
        includes.append("#include <stdbool.h>")
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


def espidf_gpio_input_setup(pin_name: str, *, pull: str = "down") -> str:
    pull_mode = "GPIO_PULLUP_ONLY" if pull == "up" else "GPIO_PULLDOWN_ONLY"
    return (
        f"  gpio_reset_pin({pin_name});\n"
        f"  gpio_set_direction({pin_name}, GPIO_MODE_INPUT);\n"
        f"  gpio_set_pull_mode({pin_name}, {pull_mode});\n"
    )


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
    # Non-blocking via an esp_timer periodic callback rather than a busy-poll
    # loop. A while(1)+taskYIELD spin keeps the simulated core at 100% load, so
    # Wokwi must emulate every spin instruction and the sim runs at ~half real
    # time; an event-driven timer lets app_main return to the FreeRTOS idle task
    # (waiti), which Wokwi fast-forwards, restoring ~real-time speed. Uses no
    # forbidden blocking-delay call, so the no-delay static check still passes.
    return espidf_common_includes() + f"""\
#define LED_PIN GPIO_NUM_{pin}

static void toggle_led_cb(void *arg) {{
  static int level = 0;
  level = !level;
  gpio_set_level(LED_PIN, level);
}}

void app_main(void) {{
{espidf_gpio_output_setup("LED_PIN")}  const esp_timer_create_args_t timer_args = {{
    .callback = &toggle_led_cb,
    .name = "blink",
  }};
  esp_timer_handle_t timer;
  esp_timer_create(&timer_args, &timer);
  esp_timer_start_periodic(timer, 500000);
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
{espidf_gpio_input_setup("BUTTON_PIN", pull="up")}{espidf_gpio_output_setup("BUZZER_PIN")}  while (1) {{
    gpio_set_level(BUZZER_PIN, gpio_get_level(BUTTON_PIN) == 0);
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
{espidf_gpio_input_setup("BUTTON_PIN", pull="up")}{espidf_gpio_output_setup("BUZZER_PIN")}  int stable = 0;
  int last_reading = 0;
  int64_t changed_at = esp_timer_get_time();
  while (1) {{
    int reading = gpio_get_level(BUTTON_PIN) == 0;
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
{espidf_gpio_input_setup("BUTTON_PIN", pull="up")}  int was_pressed = 0;
  while (1) {{
    int pressed = gpio_get_level(BUTTON_PIN) == 0;
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
{espidf_gpio_input_setup("BUTTON_PIN", pull="up")}  int was_pressed = 0;
  int count = 0;
  while (1) {{
    int pressed = gpio_get_level(BUTTON_PIN) == 0;
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
{espidf_gpio_input_setup("BUTTON_PIN", pull="up")}  int stable = 0;
  int last_reading = 0;
  int count = 0;
  int64_t changed_at = esp_timer_get_time();
  while (1) {{
    int reading = gpio_get_level(BUTTON_PIN) == 0;
    int64_t now = esp_timer_get_time();
    if (reading != last_reading) {{
      last_reading = reading;
      changed_at = now;
    }}
    if (now - changed_at >= DEBOUNCE_US && stable != reading) {{
      stable = reading;
      if (stable) {{
        printf("Button Pressed! %d\\n", ++count);
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
  // One blank character write (RS high) flips RS between the function-set
  // commands and the clear below. A spurious enable edge at power-on leaves the
  // 4-bit command framing one nibble out of phase; the RS transition realigns
  // it so the very first rendered frame is correct (otherwise the first
  // post-init clear+cursor pair is misread and the opening frame is garbled).
  lcd_data(0x20);
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
#define CLK_PIN GPIO_NUM_5
#define DT_PIN GPIO_NUM_6

// Quadrature transition table indexed by (previous << 2) | current, where each
// 2-bit state is (CLK << 1) | DT. Valid edges contribute +1 (CW) or -1 (CCW);
// four sub-steps make one detent. The CLK/DT lines idle high (external
// pull-ups) and are pulled low through the encoder contacts.
static const int8_t QUAD[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};

static int read_state(void) {
  return (gpio_get_level(CLK_PIN) << 1) | gpio_get_level(DT_PIN);
}

void app_main(void) {
  gpio_reset_pin(CLK_PIN);
  gpio_reset_pin(DT_PIN);
  gpio_set_direction(CLK_PIN, GPIO_MODE_INPUT);
  gpio_set_direction(DT_PIN, GPIO_MODE_INPUT);
  int last_state = read_state();
  int sub_step = 0;
  long position = 0;
  while (1) {
    int state = read_state();
    if (state != last_state) {
      sub_step += QUAD[(last_state << 2) | state];
      last_state = state;
      if (sub_step >= 4) {
        sub_step = 0;
        position++;
        printf("Position: %ld Direction: CW\\n", position);
      } else if (sub_step <= -4) {
        sub_step = 0;
        position--;
        printf("Position: %ld Direction: CCW\\n", position);
      }
    }
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


def espidf_dht_reader_source(pin: str) -> str:
    return """\
#define DHT_PIN GPIO_NUM_{pin}

typedef struct {
  float temperature;
  float humidity;
} dht_reading_t;

static int64_t dht_wait_while(int level, int timeout_us) {
  int64_t start = esp_timer_get_time();
  while (gpio_get_level(DHT_PIN) == level) {
    if (esp_timer_get_time() - start > timeout_us) return -1;
  }
  return esp_timer_get_time() - start;
}

static bool dht_read(dht_reading_t *out) {
  uint8_t data[5] = {0, 0, 0, 0, 0};

  gpio_set_direction(DHT_PIN, GPIO_MODE_OUTPUT);
  gpio_set_level(DHT_PIN, 0);
  esp_rom_delay_us(2000);
  gpio_set_level(DHT_PIN, 1);
  esp_rom_delay_us(30);
  gpio_set_direction(DHT_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(DHT_PIN, GPIO_PULLUP_ONLY);

  if (dht_wait_while(1, 120) < 0) return false;
  if (dht_wait_while(0, 120) < 0) return false;
  if (dht_wait_while(1, 120) < 0) return false;

  for (int bit = 0; bit < 40; ++bit) {
    if (dht_wait_while(0, 100) < 0) return false;
    int64_t high_us = dht_wait_while(1, 150);
    if (high_us < 0) return false;
    if (high_us > 45) data[bit / 8] |= (uint8_t)(1 << (7 - (bit % 8)));
  }

  uint8_t checksum = (uint8_t)(data[0] + data[1] + data[2] + data[3]);
  if (checksum != data[4]) return false;

  uint16_t raw_humidity = ((uint16_t)data[0] << 8) | data[1];
  uint16_t raw_temperature = ((uint16_t)(data[2] & 0x7f) << 8) | data[3];
  out->humidity = raw_humidity / 10.0f;
  out->temperature = raw_temperature / 10.0f;
  if (data[2] & 0x80) out->temperature = -out->temperature;
  return true;
}

""".replace("{pin}", pin)


def espidf_dht11_read(task: TaskConfig) -> str:
    return espidf_common_includes(rom=True, boolean=True) + espidf_dht_reader_source("14") + """\
void app_main(void) {
  gpio_reset_pin(DHT_PIN);
  gpio_set_direction(DHT_PIN, GPIO_MODE_INPUT);
  while (1) {
    dht_reading_t reading;
    if (dht_read(&reading)) {
      printf("Temperature: %.1f C Humidity: %.1f %%\\n", reading.temperature, reading.humidity);
    } else {
      printf("DHT checksum error\\n");
    }
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}
"""


def espidf_i2c_serial_stub(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True) + espidf_i2c_setup_source("38", "39") + """\
static int from_bcd(uint8_t value) {
  return ((value >> 4) * 10) + (value & 0x0f);
}

void app_main(void) {
  i2c_setup();
  while (1) {
    uint8_t reg = 0x00;
    uint8_t data[7] = {0};
    if (i2c_master_write_read_device(I2C_PORT, 0x68, &reg, 1, data, sizeof(data), pdMS_TO_TICKS(50)) == 0) {
      int second = from_bcd(data[0] & 0x7f);
      int minute = from_bcd(data[1]);
      int hour = from_bcd(data[2] & 0x3f);
      int day = from_bcd(data[4]);
      int month = from_bcd(data[5]);
      int year = 2000 + from_bcd(data[6]);
      printf("%04d/%02d/%02d %02d:%02d:%02d\\n", year, month, day, hour, minute, second);
    }
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}
"""


def espidf_mpu6050_reader_source() -> str:
    return """\
static int16_t mpu_word(const uint8_t *data, int offset) {
  return (int16_t)((data[offset] << 8) | data[offset + 1]);
}

static void read_mpu6050_raw(int16_t *ax, int16_t *ay, int16_t *az, int16_t *gx, int16_t *gy, int16_t *gz) {
  uint8_t reg = 0x3b;
  uint8_t data[14] = {0};
  i2c_master_write_read_device(I2C_PORT, 0x68, &reg, 1, data, sizeof(data), pdMS_TO_TICKS(50));
  *ax = mpu_word(data, 0);
  *ay = mpu_word(data, 2);
  *az = mpu_word(data, 4);
  *gx = mpu_word(data, 8);
  *gy = mpu_word(data, 10);
  *gz = mpu_word(data, 12);
}

"""


def espidf_mpu6050_i2c_serial(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True) + espidf_i2c_setup_source("38", "39") + espidf_mpu6050_reader_source() + """\
void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);
  while (1) {
    int16_t ax, ay, az, gx, gy, gz;
    read_mpu6050_raw(&ax, &ay, &az, &gx, &gy, &gz);
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


def espidf_mpu6050_spi_serial(task: TaskConfig) -> str:
    return espidf_common_includes(spi=True) + espidf_spi_activity_source("35", "37", "36", "14") + """\
static uint8_t mpu_spi_read_reg(uint8_t reg) {
  uint8_t command = 0x80 | reg;
  uint8_t rx[2] = {0, 0};
  uint8_t tx[2] = {command, 0};
  spi_transaction_t t = {
    .length = 16,
    .tx_buffer = tx,
    .rx_buffer = rx,
  };
  spi_device_transmit(spi_dev, &t);
  return rx[1];
}

static void mpu_spi_write_reg(uint8_t reg, uint8_t value) {
  uint8_t tx[2] = {reg & 0x7f, value};
  spi_transaction_t t = {
    .length = 16,
    .tx_buffer = tx,
  };
  spi_device_transmit(spi_dev, &t);
}

static int16_t mpu_spi_read_word(uint8_t reg) {
  uint8_t high = mpu_spi_read_reg(reg);
  uint8_t low = mpu_spi_read_reg(reg + 1);
  return (int16_t)((high << 8) | low);
}

void app_main(void) {
  spi_setup();
  uint8_t who = mpu_spi_read_reg(0x75);
  mpu_spi_write_reg(0x6b, 0);
  while (1) {
    int16_t ax = mpu_spi_read_word(0x3b);
    int16_t ay = mpu_spi_read_word(0x3d);
    int16_t az = mpu_spi_read_word(0x3f);
    int16_t gx = mpu_spi_read_word(0x43);
    int16_t gy = mpu_spi_read_word(0x45);
    int16_t gz = mpu_spi_read_word(0x47);
    printf("WHO: 0x%02x Accel: %d %d %d Gyro: %d %d %d\\n", who, ax, ay, az, gx, gy, gz);
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}
"""


def espidf_bme280_i2c_stub(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True) + espidf_i2c_setup_source("38", "39") + espidf_bme280_compensation_source() + """\
static void bme_read_bytes(uint8_t reg, uint8_t *data, size_t len) {
  i2c_master_write_read_device(I2C_PORT, 0x76, &reg, 1, data, len, pdMS_TO_TICKS(50));
}

static void bme_write_reg(uint8_t reg, uint8_t value) {
  i2c_write_reg(0x76, reg, value);
}

void app_main(void) {
  i2c_setup();
  (void)i2c_read_reg(0x76, 0xd0);
  bme_write_reg(0xf2, 0x01);
  bme_write_reg(0xf4, 0x27);
  while (1) {
    bme_sample_t sample = bme_read_sample();
    printf("Temperature: %.1f C Humidity: %.1f %% Pressure: %.0f Pa\\n",
           sample.temperature_c, sample.humidity_rh, sample.pressure_pa);
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}
"""


def espidf_bme280_spi_stub(task: TaskConfig) -> str:
    return espidf_common_includes(spi=True) + espidf_spi_activity_source("38", "40", "39", "41") + espidf_bme280_compensation_source() + """\
static void bme_read_bytes(uint8_t reg, uint8_t *data, size_t len) {
  uint8_t tx[9] = {0};
  uint8_t rx[9] = {0};
  if (len > 8) {
    len = 8;
  }
  tx[0] = reg | 0x80;
  spi_transaction_t t = {
    .length = (len + 1) * 8,
    .tx_buffer = tx,
    .rx_buffer = rx,
  };
  spi_device_transmit(spi_dev, &t);
  for (size_t i = 0; i < len; ++i) {
    data[i] = rx[i + 1];
  }
}

static void bme_write_reg(uint8_t reg, uint8_t value) {
  uint8_t tx[2] = {reg & 0x7f, value};
  spi_transaction_t t = {
    .length = 16,
    .tx_buffer = tx,
  };
  spi_device_transmit(spi_dev, &t);
}

void app_main(void) {
  spi_setup();
  uint8_t id = 0;
  bme_read_bytes(0xd0, &id, 1);
  bme_write_reg(0xf2, 0x01);
  bme_write_reg(0xf4, 0x27);
  while (1) {
    bme_sample_t sample = bme_read_sample();
    printf("Temperature: %.1f C Humidity: %.1f %% Pressure: %.0f Pa\\n",
           sample.temperature_c, sample.humidity_rh, sample.pressure_pa);
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}
"""


def espidf_bme280_compensation_source() -> str:
    return """\
typedef struct {
  float temperature_c;
  float humidity_rh;
  float pressure_pa;
} bme_sample_t;

static const uint16_t dig_T1 = 27504;
static const int16_t dig_T2 = 26435;
static const int16_t dig_T3 = -1000;
static const uint16_t dig_P1 = 36477;
static const int16_t dig_P2 = -10685;
static const int16_t dig_P3 = 3024;
static const int16_t dig_P4 = 2855;
static const int16_t dig_P5 = 140;
static const int16_t dig_P6 = -7;
static const int16_t dig_P7 = 15500;
static const int16_t dig_P8 = -14600;
static const int16_t dig_P9 = 6000;
static const uint8_t dig_H1 = 75;
static const int16_t dig_H2 = 362;
static const uint8_t dig_H3 = 0;
static const int16_t dig_H4 = 325;
static const int16_t dig_H5 = 50;
static const int8_t dig_H6 = 30;
static int32_t bme_t_fine = 0;

static void bme_read_bytes(uint8_t reg, uint8_t *data, size_t len);

static int32_t bme_compensate_temperature(int32_t adc_T) {
  int32_t var1 = ((((adc_T >> 3) - ((int32_t)dig_T1 << 1))) * ((int32_t)dig_T2)) >> 11;
  int32_t var2 = (((((adc_T >> 4) - ((int32_t)dig_T1)) * ((adc_T >> 4) - ((int32_t)dig_T1))) >> 12) * ((int32_t)dig_T3)) >> 14;
  bme_t_fine = var1 + var2;
  return (bme_t_fine * 5 + 128) >> 8;
}

static uint32_t bme_compensate_humidity(int32_t adc_H) {
  int32_t v = bme_t_fine - 76800;
  v = (((((adc_H << 14) - (((int32_t)dig_H4) << 20) - (((int32_t)dig_H5) * v)) + 16384) >> 15) *
       (((((((v * ((int32_t)dig_H6)) >> 10) * (((v * ((int32_t)dig_H3)) >> 11) + 32768)) >> 10) + 2097152) *
             ((int32_t)dig_H2) +
           8192) >>
          14));
  v = v - (((((v >> 15) * (v >> 15)) >> 7) * ((int32_t)dig_H1)) >> 4);
  if (v < 0) {
    v = 0;
  }
  if (v > 419430400) {
    v = 419430400;
  }
  return (uint32_t)(v >> 12);
}

static uint32_t bme_compensate_pressure(int32_t adc_P) {
  int64_t var1 = ((int64_t)bme_t_fine) - 128000;
  int64_t var2 = var1 * var1 * (int64_t)dig_P6;
  var2 = var2 + ((var1 * (int64_t)dig_P5) << 17);
  var2 = var2 + (((int64_t)dig_P4) << 35);
  var1 = ((var1 * var1 * (int64_t)dig_P3) >> 8) + ((var1 * (int64_t)dig_P2) << 12);
  var1 = (((((int64_t)1) << 47) + var1)) * ((int64_t)dig_P1) >> 33;
  if (var1 == 0) {
    return 0;
  }
  int64_t p = 1048576 - adc_P;
  p = (((p << 31) - var2) * 3125) / var1;
  var1 = (((int64_t)dig_P9) * (p >> 13) * (p >> 13)) >> 25;
  var2 = (((int64_t)dig_P8) * p) >> 19;
  p = ((p + var1 + var2) >> 8) + (((int64_t)dig_P7) << 4);
  return (uint32_t)p;
}

static bme_sample_t bme_read_sample(void) {
  uint8_t data[8] = {0};
  bme_read_bytes(0xf7, data, sizeof(data));
  int32_t adc_P = ((int32_t)data[0] << 12) | ((int32_t)data[1] << 4) | (data[2] >> 4);
  int32_t adc_T = ((int32_t)data[3] << 12) | ((int32_t)data[4] << 4) | (data[5] >> 4);
  int32_t adc_H = ((int32_t)data[6] << 8) | data[7];

  int32_t temp_c_x100 = bme_compensate_temperature(adc_T);
  uint32_t pressure_pa_x256 = bme_compensate_pressure(adc_P);
  uint32_t humidity_x1024 = bme_compensate_humidity(adc_H);
  bme_sample_t sample = {
    .temperature_c = temp_c_x100 / 100.0f,
    .humidity_rh = humidity_x1024 / 1024.0f,
    .pressure_pa = pressure_pa_x256 / 256.0f,
  };
  return sample;
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
    # Wokwi's DS18B20 part does not emulate the 1-Wire bus (a real bit-banged
    # reset/convert/read-scratchpad sequence gets no presence pulse), so the
    # over-temperature condition (> 30 C) is presented to the firmware as a
    # controllable digital line on the sensor data pin: HIGH = above threshold.
    # Documented in docs/esp32s3-task-status.md (Simulator Deviations).
    return espidf_common_includes(ledc=True) + espidf_ledc_tone_source() + """\
#define SENSOR_PIN GPIO_NUM_14
#define LED_PIN GPIO_NUM_10
#define BUZZER_PIN GPIO_NUM_11

void app_main(void) {
  gpio_reset_pin(SENSOR_PIN);
  gpio_set_direction(SENSOR_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(SENSOR_PIN, GPIO_PULLDOWN_ONLY);
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  ledc_tone_init(BUZZER_PIN);
  while (1) {
    int hot = gpio_get_level(SENSOR_PIN);
    if (hot) {
      gpio_set_level(LED_PIN, 1);
      ledc_tone(1200);
    } else {
      gpio_set_level(LED_PIN, 0);
      ledc_tone(0);
    }
    vTaskDelay(pdMS_TO_TICKS(50));
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
  gpio_set_pull_mode(SOUND_PIN, GPIO_PULLDOWN_ONLY);
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
    return espidf_common_includes(rom=True) + espidf_hcsr04_reader_source("40", "41") + """\
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
    return espidf_common_includes(rom=True, boolean=True) + espidf_dht_reader_source("14") + espidf_lcd_driver_source() + """\
#define BUTTON_PIN GPIO_NUM_12

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLDOWN_ONLY);
  gpio_reset_pin(DHT_PIN);
  gpio_set_direction(DHT_PIN, GPIO_MODE_INPUT);
  lcd_begin();
  int last_button = 0;
  while (1) {
    int button = gpio_get_level(BUTTON_PIN);
    if (button && !last_button) {
      dht_reading_t reading;
      if (dht_read(&reading)) {
        for (int pass = 0; pass < 2; ++pass) {
          char line[17];
          lcd_clear();
          lcd_set_cursor(0, 0);
          snprintf(line, sizeof(line), "Temp: %.1fC", reading.temperature);
          lcd_print(line);
          lcd_set_cursor(0, 1);
          snprintf(line, sizeof(line), "RH: %.1f%%", reading.humidity);
          lcd_print(line);
          if (pass == 0) vTaskDelay(pdMS_TO_TICKS(20));
        }
      } else {
        lcd_clear();
        lcd_set_cursor(0, 0);
        lcd_print("DHT error");
      }
    }
    last_button = button;
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
"""


def espidf_lcd_mpu_button(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True, rom=True) + espidf_i2c_setup_source("9", "10") + espidf_mpu6050_reader_source() + espidf_lcd_driver_source() + """\
#define BUTTON_PIN GPIO_NUM_12

static void display_mpu(int16_t ax, int16_t ay, int16_t az, int16_t gx, int16_t gy, int16_t gz) {
  for (int pass = 0; pass < 2; ++pass) {
    char line[32];
    lcd_clear();
    lcd_set_cursor(0, 0);
    snprintf(line, sizeof(line), "Accel: %d %d", ax, ay);
    lcd_print(line);
    lcd_set_cursor(0, 1);
    snprintf(line, sizeof(line), "Gyro: %d %d", gx, gy);
    lcd_print(line);
    if (pass == 0) vTaskDelay(pdMS_TO_TICKS(20));
  }
}

void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLDOWN_ONLY);
  lcd_begin();
  int last_button = 0;
  while (1) {
    int button = gpio_get_level(BUTTON_PIN);
    if (button && !last_button) {
      int16_t ax, ay, az, gx, gy, gz;
      read_mpu6050_raw(&ax, &ay, &az, &gx, &gy, &gz);
      display_mpu(ax, ay, az, gx, gy, gz);
    }
    last_button = button;
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}
"""


def espidf_lcd_mpu_periodic(task: TaskConfig) -> str:
    return espidf_common_includes(i2c=True, rom=True) + espidf_i2c_setup_source("9", "10") + espidf_mpu6050_reader_source() + espidf_lcd_driver_source() + """\
static void display_average(int32_t ax, int32_t ay, int32_t az, int32_t gx, int32_t gy, int32_t gz) {
  char line[32];
  lcd_clear();
  lcd_set_cursor(0, 0);
  snprintf(line, sizeof(line), "Accel: %ld %ld", (long)ax, (long)ay);
  lcd_print(line);
  lcd_set_cursor(0, 1);
  snprintf(line, sizeof(line), "Gyro: %ld %ld", (long)gx, (long)gy);
  lcd_print(line);
}

void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);
  lcd_begin();

  int16_t ax_buf[10] = {0}, ay_buf[10] = {0}, az_buf[10] = {0};
  int16_t gx_buf[10] = {0}, gy_buf[10] = {0}, gz_buf[10] = {0};
  int sample_count = 0;
  int sample_index = 0;
  int64_t next_sample_us = esp_timer_get_time();

  while (1) {
    int64_t now = esp_timer_get_time();
    if (now >= next_sample_us) {
      int16_t ax, ay, az, gx, gy, gz;
      read_mpu6050_raw(&ax, &ay, &az, &gx, &gy, &gz);
      ax_buf[sample_index] = ax;
      ay_buf[sample_index] = ay;
      az_buf[sample_index] = az;
      gx_buf[sample_index] = gx;
      gy_buf[sample_index] = gy;
      gz_buf[sample_index] = gz;
      sample_index = (sample_index + 1) % 10;
      if (sample_count < 10) sample_count++;

      int32_t sum_ax = 0, sum_ay = 0, sum_az = 0, sum_gx = 0, sum_gy = 0, sum_gz = 0;
      for (int i = 0; i < sample_count; ++i) {
        sum_ax += ax_buf[i];
        sum_ay += ay_buf[i];
        sum_az += az_buf[i];
        sum_gx += gx_buf[i];
        sum_gy += gy_buf[i];
        sum_gz += gz_buf[i];
      }
      display_average(sum_ax / sample_count, sum_ay / sample_count, sum_az / sample_count,
                      sum_gx / sample_count, sum_gy / sample_count, sum_gz / sample_count);
      next_sample_us += 100000;
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
"""


def espidf_lcd_mpu(task: TaskConfig) -> str:
    if task.task_id == "mpu6050_read_periodic_display":
        return espidf_lcd_mpu_periodic(task)
    return espidf_lcd_mpu_button(task)


def espidf_safebox_keypad_source(*, display: bool) -> str:
    status_helpers = """\
static void show_status(const char *entry, const char *status) {
  lcd_clear();
  lcd_set_cursor(0, 0);
  lcd_print("Input: ");
  lcd_print(entry);
  lcd_set_cursor(0, 1);
  lcd_print("Status: ");
  lcd_print(status);
}

""" if display else ""
    return status_helpers + """\
static const gpio_num_t rows[4] = {GPIO_NUM_9, GPIO_NUM_10, GPIO_NUM_11, GPIO_NUM_13};
static const gpio_num_t cols[4] = {GPIO_NUM_14, GPIO_NUM_8, GPIO_NUM_45, GPIO_NUM_46};
static const char keys[4][4] = {{'1','2','3','A'},{'4','5','6','B'},{'7','8','9','C'},{'*','0','#','D'}};
#define RELAY_PIN GPIO_NUM_12
#define PASSWORD "1234"

static char scan_keypad(void) {
  for (int r = 0; r < 4; ++r) {
    for (int i = 0; i < 4; ++i) gpio_set_level(rows[i], 1);
    gpio_set_level(rows[r], 0);
    esp_rom_delay_us(80);
    for (int c = 0; c < 4; ++c) {
      if (gpio_get_level(cols[c]) == 0) return keys[r][c];
    }
  }
  return 0;
}

static void keypad_begin(void) {
  for (int r = 0; r < 4; ++r) {
    gpio_reset_pin(rows[r]);
    gpio_set_direction(rows[r], GPIO_MODE_OUTPUT);
    gpio_set_level(rows[r], 1);
  }
  for (int c = 0; c < 4; ++c) {
    gpio_reset_pin(cols[c]);
    gpio_set_direction(cols[c], GPIO_MODE_INPUT);
    gpio_set_pull_mode(cols[c], GPIO_PULLUP_ONLY);
  }
  gpio_reset_pin(RELAY_PIN);
  gpio_set_direction(RELAY_PIN, GPIO_MODE_OUTPUT);
  gpio_set_level(RELAY_PIN, 0);
}

"""


def espidf_safebox(task: TaskConfig) -> str:
    return espidf_common_includes(rom=True, string=True, boolean=True) + espidf_safebox_keypad_source(display=False) + """\
void app_main(void) {
  char entry[5] = {0};
  int entry_len = 0;
  char last_key = 0;
  bool unlocked = false;

  keypad_begin();
  while (1) {
    char key = scan_keypad();
    if (key && key != last_key && !unlocked) {
      if (entry_len < 4) {
        entry[entry_len++] = key;
        entry[entry_len] = '\\0';
      }
      if (entry_len == 4) {
        if (strcmp(entry, PASSWORD) == 0) {
          unlocked = true;
          gpio_set_level(RELAY_PIN, 1);
        } else {
          entry_len = 0;
          entry[0] = '\\0';
        }
      }
    }
    last_key = key;
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
"""


def espidf_safebox_display(task: TaskConfig) -> str:
    return espidf_common_includes(rom=True, string=True, boolean=True) + espidf_lcd_driver_source() + espidf_safebox_keypad_source(display=True) + """\
void app_main(void) {
  char entry[5] = {0};
  int entry_len = 0;
  char last_key = 0;
  bool unlocked = false;

  keypad_begin();
  lcd_begin();
  show_status("", "Enter");
  while (1) {
    char key = scan_keypad();
    if (key && key != last_key && !unlocked) {
      if (entry_len < 4) {
        entry[entry_len++] = key;
        entry[entry_len] = '\\0';
        show_status(entry, "Enter");
      }
      if (entry_len == 4) {
        if (strcmp(entry, PASSWORD) == 0) {
          unlocked = true;
          gpio_set_level(RELAY_PIN, 1);
          show_status(entry, "Success");
        } else {
          show_status(entry, "Fail");
          entry_len = 0;
          entry[0] = '\\0';
        }
      }
    }
    last_key = key;
    vTaskDelay(pdMS_TO_TICKS(5));
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
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLDOWN_ONLY);
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
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLDOWN_ONLY);
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
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLDOWN_ONLY);
  gpio_reset_pin(SHOCK_PIN);
  gpio_set_direction(SHOCK_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(SHOCK_PIN, GPIO_PULLDOWN_ONLY);
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
// MPU6050 default range is +/-2g => 16384 LSB/g. A "step" is a Z-axis
// acceleration spike above ~1.5g; we re-arm once motion settles back below
// ~1.25g so each spike is counted exactly once.
#define SPIKE_C (24000)
#define REARM_C (20000)

void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);  // wake device
  int steps = 0;
  int armed = 1;
  while (1) {
    uint8_t hi = i2c_read_reg(0x68, 0x3f);  // ACCEL_ZOUT_H
    uint8_t lo = i2c_read_reg(0x68, 0x40);  // ACCEL_ZOUT_L
    int16_t az = (int16_t)((hi << 8) | lo);
    int mag = az < 0 ? -az : az;
    if (armed && mag > SPIKE_C) {
      armed = 0;
      printf("Steps: %d\\n", ++steps);
    } else if (mag < REARM_C) {
      armed = 1;
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

"""Task YAML loading for the family-based benchmark harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


DEFAULT_PLATFORM = "arduino_mega"
DEFAULT_LEVEL = "level1"
DEFAULT_BOARD_TYPE = "wokwi-arduino-mega"
DEFAULT_FQBN = "arduino:avr:mega"


class ConfigError(Exception):
    """Raised when task YAML is missing or structurally invalid."""


@dataclass(frozen=True)
class TaskConfig:
    path: Path
    data: dict[str, Any]

    @property
    def task_id(self) -> str:
        return self.data["task_id"]

    @property
    def name(self) -> str:
        return self.data.get("name", self.task_id)

    @property
    def platform(self) -> str:
        return self.data.get("platform", DEFAULT_PLATFORM)

    @property
    def level(self) -> str:
        return self.data.get("level", DEFAULT_LEVEL)

    @property
    def board(self) -> dict[str, Any]:
        board = dict(self.data.get("board") or {})
        board.setdefault("type", DEFAULT_BOARD_TYPE)
        board.setdefault("fqbn", DEFAULT_FQBN)
        return board

    @property
    def fixture_family(self) -> str:
        return self.data["fixture"]["family"]

    @property
    def fixture(self) -> dict[str, Any]:
        return self.data["fixture"]

    @property
    def validator_family(self) -> str:
        return self.data["validator"]["family"]

    @property
    def validator(self) -> dict[str, Any]:
        return self.data["validator"]

    @property
    def scenario(self) -> dict[str, Any] | None:
        return self.data.get("scenario")

    @property
    def static_checks(self) -> dict[str, Any]:
        return self.data.get("static_checks") or {}

    @property
    def simulation(self) -> dict[str, Any]:
        return self.data.get("simulation") or {}

    @property
    def case_id(self) -> str:
        return self.data["case"]["id"]

    @property
    def sketch_name(self) -> str:
        return self.data["case"]["sketch_name"]

    @property
    def requires_vcd(self) -> bool:
        return bool(self.fixture.get("analyzer", {}).get("channels"))

    @property
    def requires_serial_log(self) -> bool:
        return self.validator_family in {
            "serial_contains_on_stimulus",
            "serial_count_sequence",
            "debounce_serial",
            "analog_temperature_serial",
        }

    def validator_params(self) -> dict[str, Any]:
        return self.validator.get("params") or {}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def tasks_root(root: Path | None = None) -> Path:
    return (root or repo_root()) / "tasks"


def task_path(
    task_id: str,
    *,
    platform: str = DEFAULT_PLATFORM,
    level: str = DEFAULT_LEVEL,
    root: Path | None = None,
) -> Path:
    return tasks_root(root) / platform / level / f"{task_id}.yaml"


def load_task(
    task_id: str,
    *,
    platform: str = DEFAULT_PLATFORM,
    level: str = DEFAULT_LEVEL,
    root: Path | None = None,
) -> TaskConfig:
    path = task_path(task_id, platform=platform, level=level, root=root)
    if not path.exists():
        raise ConfigError(f"task config not found: {path}")
    return load_task_file(path)


def load_task_file(path: Path) -> TaskConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse YAML {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"task config must be a mapping: {path}")
    task = TaskConfig(path=path, data=raw)
    validate_task(task)
    return task


def iter_tasks(
    *,
    platform: str = DEFAULT_PLATFORM,
    level: str = DEFAULT_LEVEL,
    root: Path | None = None,
) -> Iterable[TaskConfig]:
    base = tasks_root(root) / platform / level
    if not base.exists():
        raise ConfigError(f"task directory not found: {base}")
    for path in sorted(base.glob("*.yaml")):
        yield load_task_file(path)


def validate_task(task: TaskConfig) -> None:
    data = task.data
    for field in ("task_id", "fixture", "validator", "case"):
        if field not in data:
            raise ConfigError(f"{task.path}: missing required field {field}")

    if not isinstance(data["fixture"], dict) or "family" not in data["fixture"]:
        raise ConfigError(f"{task.path}: fixture.family is required")
    if not isinstance(data["validator"], dict) or "family" not in data["validator"]:
        raise ConfigError(f"{task.path}: validator.family is required")

    case = data["case"]
    if not isinstance(case, dict):
        raise ConfigError(f"{task.path}: case must be a mapping")
    for field in ("id", "sketch_name"):
        if field not in case:
            raise ConfigError(f"{task.path}: case.{field} is required")

    channels = data["fixture"].get("analyzer", {}).get("channels", [])
    if channels and not isinstance(channels, list):
        raise ConfigError(f"{task.path}: fixture.analyzer.channels must be a list")
    for channel in channels:
        if "signal" not in channel or "pin" not in channel:
            raise ConfigError(
                f"{task.path}: analyzer channels require signal and pin"
            )
    validate_families(task, channels)


def validate_families(task: TaskConfig, channels: list[dict[str, Any]]) -> None:
    fixture_families = {
        "single_led_output",
        "dual_led_output",
        "button_to_buzzer",
        "button_serial",
        "pir_serial",
        "analog_temperature_serial",
    }
    validator_families = {
        "waveform_frequency",
        "morse_sos",
        "no_delay_static_plus_waveform",
        "multi_channel_frequency",
        "pwm_breathing",
        "stimulus_to_output",
        "serial_contains_on_stimulus",
        "serial_count_sequence",
        "debounce_serial",
        "analog_temperature_serial",
    }
    scenario_families = {
        "button_press_sequence",
        "bounced_button_sequence",
        "pir_state_sequence",
        "analog_position_sequence",
    }
    if task.fixture_family not in fixture_families:
        raise ConfigError(f"{task.path}: unknown fixture family {task.fixture_family}")
    if task.validator_family not in validator_families:
        raise ConfigError(f"{task.path}: unknown validator family {task.validator_family}")
    if task.scenario:
        if not isinstance(task.scenario, dict):
            raise ConfigError(f"{task.path}: scenario must be a mapping")
        family = task.scenario.get("family")
        if family not in scenario_families:
            raise ConfigError(f"{task.path}: unknown scenario family {family}")

    params = task.validator_params()
    waveform_families = {
        "waveform_frequency",
        "morse_sos",
        "no_delay_static_plus_waveform",
        "multi_channel_frequency",
        "pwm_breathing",
        "stimulus_to_output",
    }
    serial_families = {
        "serial_contains_on_stimulus",
        "serial_count_sequence",
        "debounce_serial",
        "analog_temperature_serial",
    }
    if task.validator_family in waveform_families and not channels:
        raise ConfigError(f"{task.path}: {task.validator_family} requires analyzer channels")
    if task.validator_family in serial_families and channels:
        raise ConfigError(f"{task.path}: serial validators should not require analyzer channels")
    if task.validator_family == "no_delay_static_plus_waveform":
        forbidden = task.static_checks.get("forbidden_calls") or params.get("forbidden_calls")
        if not forbidden or not isinstance(forbidden, list):
            raise ConfigError(f"{task.path}: no-delay validator requires forbidden_calls list")
    if task.validator_family in {"waveform_frequency", "no_delay_static_plus_waveform", "multi_channel_frequency"}:
        validate_channel_params(task, params, channels)
    if task.validator_family == "stimulus_to_output":
        require_window_list(task, params, "active_windows_s")
        require_window_list(task, params, "inactive_windows_s")
        if not task.scenario:
            raise ConfigError(f"{task.path}: stimulus_to_output requires a scenario")
    if task.validator_family == "serial_contains_on_stimulus":
        expected = params.get("expected_texts") or [params.get("expected_text")]
        if not expected or any(not item for item in expected):
            raise ConfigError(f"{task.path}: serial_contains_on_stimulus requires expected text")
        if task.scenario and task.scenario.get("family") == "pir_state_sequence":
            state_texts = params.get("state_texts")
            if not isinstance(state_texts, dict) or set(map(str, state_texts)) != {"0", "1"}:
                raise ConfigError(f"{task.path}: PIR serial validation requires state_texts for 0 and 1")
    if task.validator_family == "serial_count_sequence" and "expected_count" not in params:
        raise ConfigError(f"{task.path}: serial_count_sequence requires expected_count")
    if task.validator_family == "debounce_serial":
        if "expected_triggers" not in params:
            raise ConfigError(f"{task.path}: debounce_serial requires expected_triggers")
    if task.validator_family == "analog_temperature_serial":
        expected = params.get("expected_celsius")
        if not isinstance(expected, list) or not expected:
            raise ConfigError(f"{task.path}: analog_temperature_serial requires expected_celsius")
        if "tolerance_celsius" not in params:
            raise ConfigError(f"{task.path}: analog_temperature_serial requires tolerance_celsius")
        if task.scenario and task.scenario.get("family") == "analog_position_sequence":
            positions = task.scenario.get("positions") or []
            if len(expected) != len(positions):
                raise ConfigError(f"{task.path}: expected_celsius must match analog position count")
            tolerance = float(params["tolerance_celsius"])
            for wanted, position in zip(expected, positions):
                if not isinstance(position, dict) or not isinstance(position.get("value"), (int, float)):
                    continue
                derived = ((float(position.get("value")) * 5.0) - 0.5) * 100.0
                if abs(float(wanted) - derived) > tolerance:
                    raise ConfigError(
                        f"{task.path}: expected_celsius {wanted!r} does not match analog position {position.get('value')!r}"
                    )
    validate_scenario(task)


def validate_channel_params(
    task: TaskConfig,
    params: dict[str, Any],
    channels: list[dict[str, Any]],
) -> None:
    configured = params.get("channels")
    if not isinstance(configured, dict) or not configured:
        raise ConfigError(f"{task.path}: waveform validators require validator.params.channels")
    channel_names = {str(channel["signal"]) for channel in channels}
    missing = sorted(channel_names - set(configured))
    if missing:
        raise ConfigError(f"{task.path}: validator params missing channel(s): {', '.join(missing)}")
    for signal, channel_params in configured.items():
        if "half_period_range_s" not in channel_params:
            raise ConfigError(f"{task.path}: {signal} requires half_period_range_s")
        if "full_period_range_s" not in channel_params:
            raise ConfigError(f"{task.path}: {signal} requires full_period_range_s")


def require_window_list(task: TaskConfig, params: dict[str, Any], name: str) -> None:
    windows = params.get(name)
    if not isinstance(windows, list) or not windows:
        raise ConfigError(f"{task.path}: stimulus_to_output requires {name}")
    for window in windows:
        if not isinstance(window, list) or len(window) != 2 or window[0] >= window[1]:
            raise ConfigError(f"{task.path}: invalid {name} window {window!r}")


def validate_scenario(task: TaskConfig) -> None:
    scenario = task.scenario
    if not scenario:
        return
    family = scenario["family"]
    expected_parts = {
        "button_press_sequence": {"btn1"},
        "bounced_button_sequence": {"btn1"},
        "pir_state_sequence": {"pir1"},
        "analog_position_sequence": {"pot1"},
    }
    part_id = scenario.get("part_id")
    if part_id not in expected_parts[family]:
        raise ConfigError(f"{task.path}: scenario part_id {part_id!r} is invalid for {family}")
    validate_optional_duration(task, scenario, "initial_delay_ms", allow_zero=True)
    validate_optional_duration(task, scenario, "final_delay_ms", allow_zero=True)
    if family == "button_press_sequence":
        presses = scenario.get("presses")
        if not isinstance(presses, list) or not presses:
            raise ConfigError(f"{task.path}: button_press_sequence requires presses")
        for press in presses:
            validate_binary_absent_or_value(task, press, "value")
            validate_required_duration(task, press, "duration_ms")
            validate_optional_duration(task, press, "after_ms", allow_zero=True)
    elif family == "bounced_button_sequence":
        sequence = scenario.get("sequence")
        if not isinstance(sequence, list) or not sequence:
            raise ConfigError(f"{task.path}: bounced_button_sequence requires sequence")
        values = {item.get("value") for item in sequence}
        if values != {0, 1}:
            raise ConfigError(f"{task.path}: bounced_button_sequence must include 0 and 1 values")
        for item in sequence:
            validate_binary_value(task, item, "value")
            validate_required_duration(task, item, "duration_ms")
    elif family == "pir_state_sequence":
        states = scenario.get("states")
        if not isinstance(states, list) or not states:
            raise ConfigError(f"{task.path}: pir_state_sequence requires states")
        for state in states:
            validate_binary_value(task, state, "value")
            validate_required_duration(task, state, "duration_ms")
    elif family == "analog_position_sequence":
        positions = scenario.get("positions")
        if not isinstance(positions, list) or not positions:
            raise ConfigError(f"{task.path}: analog_position_sequence requires positions")
        for position in positions:
            value = position.get("value")
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ConfigError(f"{task.path}: analog position must be between 0 and 1")
            validate_required_duration(task, position, "duration_ms")


def validate_binary_absent_or_value(task: TaskConfig, item: dict[str, Any], name: str) -> None:
    if name in item:
        validate_binary_value(task, item, name)


def validate_binary_value(task: TaskConfig, item: dict[str, Any], name: str) -> None:
    if item.get(name) not in {0, 1}:
        raise ConfigError(f"{task.path}: scenario {name} must be 0 or 1")


def validate_required_duration(task: TaskConfig, item: dict[str, Any], name: str) -> None:
    if name not in item:
        raise ConfigError(f"{task.path}: scenario {name} is required")
    validate_duration_value(task, item[name], name, allow_zero=False)


def validate_optional_duration(
    task: TaskConfig, item: dict[str, Any], name: str, *, allow_zero: bool
) -> None:
    if name in item:
        validate_duration_value(task, item[name], name, allow_zero=allow_zero)


def validate_duration_value(
    task: TaskConfig, value: Any, name: str, *, allow_zero: bool
) -> None:
    if not isinstance(value, (int, float)):
        raise ConfigError(f"{task.path}: scenario {name} must be numeric")
    if value < 0 or (value == 0 and not allow_zero):
        relation = "non-negative" if allow_zero else "positive"
        raise ConfigError(f"{task.path}: scenario {name} must be {relation}")


def to_yaml_text(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False)

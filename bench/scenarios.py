"""Wokwi automation scenario generation.

Wokwi scenarios are currently an alpha API, so this module is deliberately
small and isolates that surface area from validators and task config loading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import TaskConfig


class ScenarioError(Exception):
    """Raised when a scenario family cannot be generated."""


def generate_scenario(task: TaskConfig) -> dict[str, Any] | None:
    scenario = task.scenario
    if not scenario:
        return None
    family = scenario.get("family")
    generators = {
        "button_press_sequence": button_press_sequence,
        "bounced_button_sequence": bounced_button_sequence,
        "pir_state_sequence": pir_state_sequence,
        "analog_position_sequence": analog_position_sequence,
    }
    try:
        return generators[family](task)
    except KeyError as exc:
        raise ScenarioError(f"unknown scenario family: {family}") from exc


def scenario_base(task: TaskConfig) -> dict[str, Any]:
    return {
        "name": f"{task.task_id} automation",
        "version": 1,
        "author": "IoT-Bench",
        "steps": [],
    }


def delay_step(duration_ms: int | float) -> dict[str, str]:
    return {"delay": f"{duration_ms:g}ms"}


def set_control_step(part_id: str, control: str, value: Any) -> dict[str, dict[str, Any]]:
    return {
        "set-control": {
            "part-id": part_id,
            "control": control,
            "value": value,
        }
    }


def button_press_sequence(task: TaskConfig) -> dict[str, Any]:
    config = task.scenario or {}
    part_id = config.get("part_id", "btn1")
    scenario = scenario_base(task)
    scenario["steps"].append(delay_step(config.get("initial_delay_ms", 200)))
    for press in config.get("presses", []):
        scenario["steps"].append(set_control_step(part_id, "pressed", 1))
        scenario["steps"].append(delay_step(press.get("duration_ms", 200)))
        scenario["steps"].append(set_control_step(part_id, "pressed", 0))
        scenario["steps"].append(delay_step(press.get("after_ms", 200)))
    return scenario


def bounced_button_sequence(task: TaskConfig) -> dict[str, Any]:
    config = task.scenario or {}
    part_id = config.get("part_id", "btn1")
    scenario = scenario_base(task)
    scenario["steps"].append(delay_step(config.get("initial_delay_ms", 200)))
    for item in config.get("sequence", []):
        scenario["steps"].append(set_control_step(part_id, "pressed", item["value"]))
        scenario["steps"].append(delay_step(item.get("duration_ms", 1)))
    scenario["steps"].append(set_control_step(part_id, "pressed", 0))
    scenario["steps"].append(delay_step(config.get("final_delay_ms", 250)))
    return scenario


def pir_state_sequence(task: TaskConfig) -> dict[str, Any]:
    config = task.scenario or {}
    part_id = config.get("part_id", "pir1")
    scenario = scenario_base(task)
    scenario["steps"].append(delay_step(config.get("initial_delay_ms", 200)))
    for state in config.get("states", []):
        scenario["steps"].append(set_control_step(part_id, "pressed", state["value"]))
        scenario["steps"].append(delay_step(state.get("duration_ms", 300)))
    scenario["steps"].append(set_control_step(part_id, "pressed", 0))
    return scenario


def analog_position_sequence(task: TaskConfig) -> dict[str, Any]:
    config = task.scenario or {}
    part_id = config.get("part_id", "pot1")
    scenario = scenario_base(task)
    scenario["steps"].append(delay_step(config.get("initial_delay_ms", 200)))
    for position in config.get("positions", []):
        scenario["steps"].append(set_control_step(part_id, "position", position["value"]))
        scenario["steps"].append(delay_step(position.get("duration_ms", 300)))
    return scenario


def write_scenario(path: Path, scenario: dict[str, Any] | None) -> None:
    if scenario is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")

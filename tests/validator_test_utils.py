import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIAGRAM = ROOT / "diagram.json"


def assert_classification(testcase: unittest.TestCase, args: list[str], expected: str) -> dict:
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    testcase.assertEqual(
        completed.returncode,
        0,
        msg=f"validator failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
    )
    payload = json.loads(completed.stdout)
    testcase.assertEqual(payload["classification"], expected, payload)
    testcase.assertIn("result", payload)
    testcase.assertNotIn("legacy_classification", payload)
    testcase.assertIn("failure_stage", payload)
    return payload


def validate_artifacts_args(task_id: str, case_dir: Path) -> list[str]:
    return [
        "-m",
        "bench.cli",
        "validate-artifacts",
        "--task",
        task_id,
        "--case",
        str(case_dir),
    ]


def make_case(parent: Path, case_id: str, sketch_name: str) -> Path:
    case_dir = parent / case_id
    sketch_dir = case_dir / "sketch" / sketch_name
    (case_dir / "artifacts" / "logic").mkdir(parents=True)
    sketch_dir.mkdir(parents=True)
    (case_dir / "diagram.json").write_text(DIAGRAM.read_text(encoding="utf-8"), encoding="utf-8")
    (case_dir / "wokwi.toml").write_text(
        "[wokwi]\n"
        "version = 1\n"
        f"firmware = 'artifacts/build/{sketch_name}.ino.hex'\n"
        f"elf = 'artifacts/build/{sketch_name}.ino.elf'\n"
        "vcdFile = 'artifacts/logic/wokwi.vcd'\n",
        encoding="utf-8",
    )
    write_sketch(case_dir, sketch_name, "void setup(){}\nvoid loop(){}\n")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "id": case_id,
                "paths": {
                    "sketch": f"sketch/{sketch_name}",
                    "diagram": "diagram.json",
                    "vcd": "artifacts/logic/wokwi.vcd",
                    "build": "artifacts/build",
                },
                "observed_signal": {
                    "vcd_name": "D0",
                    "expected_connection": "GPIO 3",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return case_dir


def write_sketch(case_dir: Path, sketch_name: str, source: str) -> None:
    sketch_dir = case_dir / "sketch" / sketch_name
    sketch_dir.mkdir(parents=True, exist_ok=True)
    (sketch_dir / f"{sketch_name}.ino").write_text(source, encoding="utf-8")


def update_case_vcd(case_dir: Path, vcd_path: Path) -> None:
    manifest_path = case_dir / "case.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["paths"]["vcd"] = str(vcd_path.relative_to(case_dir)).replace("\\", "/")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def write_digital_vcd(path: Path, events: list[tuple[float, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "$version synthetic validator test $end",
        "$timescale 1ns $end",
        "$scope module logic $end",
        "$var wire 1 ! D0 $end",
        "$upscope $end",
        "$enddefinitions $end",
    ]
    for timestamp_s, value in events:
        lines.append(f"#{round(timestamp_s * 1_000_000_000)}")
        lines.append(f"{value}!")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def blink_events(half_period_s: float, cycles: int) -> list[tuple[float, int]]:
    events = [(0.0, 0), (0.100, 1)]
    timestamp = 0.100
    value = 1
    for _ in range(cycles * 2):
        timestamp += half_period_s
        value = 1 - value
        events.append((timestamp, value))
    return events


def morse_sos_events(unit_s: float, dash_units: int) -> list[tuple[float, int]]:
    high_units = [1, 1, 1, dash_units, dash_units, dash_units, 1, 1, 1]
    gap_units = [1, 1, 3, 1, 1, 3, 1, 1, 7]
    events: list[tuple[float, int]] = [(0.0, 0)]
    timestamp = 0.300
    for high, gap in zip(high_units, gap_units):
        events.append((timestamp, 1))
        timestamp += high * unit_s
        events.append((timestamp, 0))
        timestamp += gap * unit_s
    return events


def write_pwm_vcd(path: Path, duty_steps: list[float]) -> None:
    events: list[tuple[float, int]] = []
    timestamp = 0.0
    pwm_period_s = 0.001
    step_s = 0.010

    def append_event(time_s: float, value: int) -> None:
        if events and abs(events[-1][0] - time_s) < 1e-15:
            events[-1] = (time_s, value)
            return
        if events and events[-1][1] == value:
            return
        events.append((time_s, value))

    append_event(0.0, 0)
    for duty in duty_steps:
        step_start = timestamp
        for cycle in range(10):
            cycle_start = step_start + cycle * pwm_period_s
            high_s = max(0.0, min(1.0, duty)) * pwm_period_s
            if high_s > 0:
                append_event(cycle_start, 1)
            if high_s < pwm_period_s:
                append_event(cycle_start + high_s, 0)
        timestamp += step_s
    append_event(timestamp + 0.020, 0)
    write_digital_vcd(path, events)

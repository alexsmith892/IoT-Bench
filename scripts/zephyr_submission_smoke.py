"""Run external Zephyr submission smoke fixtures through the public CLI path."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.config import load_task
from bench.runner import generate_case

FIXTURES = ROOT / "tests" / "fixtures" / "zephyr_submission_smoke"
PLATFORM = "zephyr_nano33ble"
EXPECTED_RESULT = "BC"


@dataclass(frozen=True)
class SmokeCase:
    family: str
    task_id: str
    level: str
    fixture: Path


SMOKE_CASES = [
    SmokeCase("single-wire", "dht11_read", "level2", Path("single_wire/dht11_read.c")),
    SmokeCase("I2C", "ds1307_rtc", "level2", Path("i2c/ds1307_rtc.c")),
    SmokeCase("SPI", "bme280_read_spi", "level2", Path("spi/bme280_read_spi.c")),
    SmokeCase("ADC", "tmp36_read", "level1", Path("adc/tmp36_read.c")),
    SmokeCase(
        "LCD+button",
        "tmp36_read_button_display",
        "level3",
        Path("lcd_button/tmp36_read_button_display.c"),
    ),
    SmokeCase("PWM", "breathing_led", "level1", Path("pwm/breathing_led.c")),
]


def run_case(case: SmokeCase) -> tuple[bool, str]:
    fixture = FIXTURES / case.fixture
    if not fixture.exists():
        return False, f"{case.family}: {case.task_id} missing fixture: {fixture}"

    try:
        task = load_task(case.task_id, platform=PLATFORM, level=case.level)
        with tempfile.TemporaryDirectory(prefix=f"iotbench-{case.task_id}-") as tmp:
            paths = generate_case(task, root=Path(tmp))
            cmd = [
                sys.executable,
                "-m",
                "bench.cli",
                "run",
                "--platform",
                PLATFORM,
                "--level",
                case.level,
                "--task",
                case.task_id,
                "--case",
                str(paths.case_dir),
                "--sketch",
                str(fixture),
            ]
            completed = subprocess.run(
                cmd,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
    except Exception as exc:
        return False, f"{case.family}: {case.task_id} smoke setup failed: {exc}"

    if completed.returncode != 0:
        return (
            False,
            f"{case.family}: {case.task_id} command failed with exit {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return (
            False,
            f"{case.family}: {case.task_id} emitted malformed JSON: {exc}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )

    result = payload.get("result")
    line = f"{case.family}: {case.task_id} result: {result}"
    if result != EXPECTED_RESULT:
        return (
            False,
            f"{line}\nexpected: {EXPECTED_RESULT}\n"
            f"reason: {payload.get('reason')}\n"
            f"classification: {payload.get('classification')}\n"
            f"failure_stage: {payload.get('failure_stage')}\n"
            f"failure_source: {payload.get('failure_source')}",
        )
    return True, line


def main() -> int:
    failures: list[str] = []
    for case in SMOKE_CASES:
        ok, message = run_case(case)
        print(message)
        if not ok:
            failures.append(message)

    if failures:
        print("\nSmoke failures:", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

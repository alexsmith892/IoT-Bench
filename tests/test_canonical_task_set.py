"""Offline guard: the local Zephyr task set must track the upstream canonical set.

The IoT-SkillsBench source of truth for tasks lives at
https://github.com/iot-agent/iot-skillsbench/tree/main/tasks (the three
``levelN-nRF52840-Zephyr.txt`` files). ``tests/fixtures/upstream_zephyr_tasks.json``
vendors those canonical task ids so this check stays offline.

This test does NOT demand exact equality today: the codebase has a known,
documented set of deviations (canonical tasks not yet *covered*, plus one
sanctioned non-canonical addition). Those are pinned in ``KNOWN_MISSING`` /
``KNOWN_EXTRA`` so the test passes now while still failing the moment NEW drift
appears in either direction.

"Covered" means present **and** supported (``support.status`` not
``unsupported``). A canonical task that only exists as an ``unsupported`` stub
still counts as pending, so the two realignment workstreams stay decoupled:
adding a stub for a KNOWN_MISSING task does not turn the suite red. The pin only
goes stale once a task gains real, supported coverage — the milestone that
matters. As Workstream B lands coverage, shrink the two sets; when both are
empty the local supported set matches upstream exactly.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from bench.config import iter_tasks

PLATFORM = "zephyr_nano33ble"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "upstream_zephyr_tasks.json"

# Canonical tasks not yet *covered* locally (absent, or present only as an
# unsupported stub). Each is blocked on a peripheral Renode does not model
# natively (see the audit's peripheral strategy):
#   dht11_read, dht11_read_button_display -> DHT11 single-wire bit-banged
#   ds18b20_heat_alarm                    -> DS18B20 1-Wire
#   bme280_read_spi                       -> BME280 over SPI
KNOWN_MISSING = {
    "dht11_read",
    "bme280_read_spi",
    "ds18b20_heat_alarm",
    "dht11_read_button_display",
}

# Local tasks with no upstream counterpart. lsm9ds1_read_i2c uses the Nano 33
# BLE's real onboard IMU; keep it here only while it is a sanctioned addition.
KNOWN_EXTRA = {
    "lsm9ds1_read_i2c",
}


def _canonical_ids() -> set[str]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for level in ("level1", "level2", "level3"):
        ids.update(data[level])
    return ids


def _local_ids() -> set[str]:
    ids: set[str] = set()
    for level in ("level1", "level2", "level3"):
        for task in iter_tasks(platform=PLATFORM, level=level):
            ids.add(task.task_id)
    return ids


def _covered_ids() -> set[str]:
    """Task ids that are present AND supported (real coverage, not a stub)."""
    ids: set[str] = set()
    for level in ("level1", "level2", "level3"):
        for task in iter_tasks(platform=PLATFORM, level=level):
            if task.is_supported:
                ids.add(task.task_id)
    return ids


class CanonicalTaskSetTests(unittest.TestCase):
    def test_no_unexpected_missing_canonical_tasks(self) -> None:
        missing = _canonical_ids() - _covered_ids()
        new_missing = missing - KNOWN_MISSING
        self.assertEqual(
            set(),
            new_missing,
            "canonical upstream task(s) lack supported coverage and are not "
            f"recorded in KNOWN_MISSING: {sorted(new_missing)}",
        )

    def test_no_unexpected_extra_tasks(self) -> None:
        extra = _local_ids() - _canonical_ids()
        new_extra = extra - KNOWN_EXTRA
        self.assertEqual(
            set(),
            new_extra,
            "local task(s) not in the upstream canonical set and not recorded "
            f"in KNOWN_EXTRA: {sorted(new_extra)}",
        )

    def test_known_deviation_lists_are_not_stale(self) -> None:
        # A KNOWN_MISSING task that has gained supported coverage, or a
        # KNOWN_EXTRA that is gone / turns out to be canonical, means the pin is
        # stale and must be cleaned up so the gate keeps biting.
        covered = _covered_ids()
        local = _local_ids()
        canonical = _canonical_ids()
        stale_missing = KNOWN_MISSING & covered
        self.assertEqual(
            set(),
            stale_missing,
            f"KNOWN_MISSING lists now-covered tasks: {sorted(stale_missing)}",
        )
        self.assertEqual(
            set(),
            KNOWN_EXTRA - local,
            f"KNOWN_EXTRA lists tasks no longer present locally: {sorted(KNOWN_EXTRA - local)}",
        )
        self.assertEqual(
            set(),
            KNOWN_EXTRA & canonical,
            f"KNOWN_EXTRA lists tasks that are actually canonical: {sorted(KNOWN_EXTRA & canonical)}",
        )


if __name__ == "__main__":
    unittest.main()

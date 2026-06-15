"""Offline structural guard: every *supported* Zephyr task must have a generated
case.

A task can declare ``support.status: supported`` (the default) yet have no
``cases/<case_id>/case.repl`` on disk. The harness only blocks ``generate`` /
``build`` / ``run`` for tasks that are explicitly *unsupported*, so a supported
task with no case is silently unverifiable: nothing builds it, nothing runs it,
and no other offline test loads it (``test_renode_regen_drift`` skips absent
cases by design, and ``test_canonical_task_set`` only checks the *set* of ids).

This is exactly the gap that left the HC-SR04 trio (``hcsr04_find_distance``,
``parking_sensor``, ``reverse_parking_sensor``) marked supported with no case.
The contract enforced here: a Zephyr task is either

- supported AND has a tracked ``case.repl`` (it is actually exercisable), or
- explicitly ``support.status: unsupported`` with a documented ``reason``.

There is no third "supported but uncased" state. To clear a failure, either
generate the case (``python -m bench.cli generate --task <id>``) or, if Renode
cannot model the peripheral soundly, mark the task unsupported with a reason.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from bench.config import iter_tasks

PLATFORM = "zephyr_nano33ble"
REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = REPO_ROOT / "cases"


def _renode_tasks():
    for level in ("level1", "level2", "level3"):
        yield from iter_tasks(platform=PLATFORM, level=level)


class ZephyrSupportedHasCaseTests(unittest.TestCase):
    def test_every_supported_task_has_generated_case_repl(self) -> None:
        uncased: list[str] = []
        for task in _renode_tasks():
            if not task.is_supported:
                continue
            repl_path = CASES_DIR / task.case_id / "case.repl"
            if not repl_path.exists():
                uncased.append(f"{task.task_id} (expected {repl_path.relative_to(REPO_ROOT)})")
        self.assertEqual(
            [],
            sorted(uncased),
            "supported Zephyr task(s) have no generated case.repl and are thus "
            "silently unverifiable; generate the case "
            "(`python -m bench.cli generate --task <id>`) or mark the task "
            f"`support.status: unsupported` with a reason: {sorted(uncased)}",
        )

    def test_guard_has_tasks_to_check(self) -> None:
        # Defend against the guard passing vacuously (e.g. a moved task tree
        # leaving zero supported tasks).
        supported = [t for t in _renode_tasks() if t.is_supported]
        self.assertTrue(
            supported,
            "no supported zephyr_nano33ble tasks found; the case guard would "
            "pass vacuously",
        )


if __name__ == "__main__":
    unittest.main()

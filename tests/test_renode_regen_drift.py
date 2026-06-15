"""Offline drift gate: every tracked Renode ``case.repl`` must still match what
``bench.renode.generate_repl`` produces from its task YAML.

``validate_renode_case`` already enforces this per task at lint/generate time,
but nothing swept *all* generated cases at once, so a backend change could
silently leave a stale tracked ``case.repl`` for a task no other test loads.
This walks the whole ``zephyr_nano33ble`` catalog.

What is and is not checked here:
- ``case.repl`` IS tracked and is a deterministic function of the task YAML, so
  it is byte-compared.
- Per-variant ``case.repl`` IS tracked; the runner emits it as a verbatim copy
  of the base repl (the platform description is variant-invariant; variant
  state lives in the per-variant ``.resc``), so each is asserted equal to the
  base repl.
- ``case.resc`` is NOT tracked (``.gitignore`` line ``cases/*/case.resc``): it
  embeds machine-specific absolute serial/VCD paths and cannot be byte-stable
  across machines. Instead its emitter is exercised through
  ``validate_renode_case`` (scenario-control + variant-scenario resolution),
  which raises on drift without needing Renode or west.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from bench.config import iter_tasks
from bench.renode import generate_repl, validate_renode_case
from bench.runner import variant_id

PLATFORM = "zephyr_nano33ble"
REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = REPO_ROOT / "cases"


def _renode_tasks():
    for level in ("level1", "level2", "level3"):
        yield from iter_tasks(platform=PLATFORM, level=level)


class RenodeRegenDriftTests(unittest.TestCase):
    def test_at_least_one_generated_case_present(self) -> None:
        # Guard against the sweep silently passing because every case dir is
        # missing (e.g. a moved cases/ tree).
        present = [
            t for t in _renode_tasks() if (CASES_DIR / t.case_id / "case.repl").exists()
        ]
        self.assertTrue(present, "no tracked Renode case.repl files found under cases/")

    def test_tracked_repl_matches_regeneration(self) -> None:
        for task in _renode_tasks():
            case_dir = CASES_DIR / task.case_id
            repl_path = case_dir / "case.repl"
            if not repl_path.exists():
                # No generated case yet (e.g. tasks still pending a case).
                # test_canonical_task_set.py tracks which tasks are missing.
                continue
            with self.subTest(task=task.task_id):
                expected = generate_repl(task)
                actual = repl_path.read_text(encoding="utf-8")
                self.assertEqual(
                    expected,
                    actual,
                    f"{repl_path} is stale; regenerate with "
                    f"`python -m bench.cli generate --task {task.task_id}`",
                )

    def test_validate_renode_case_passes_for_tracked_cases(self) -> None:
        for task in _renode_tasks():
            case_dir = CASES_DIR / task.case_id
            repl_path = case_dir / "case.repl"
            if not repl_path.exists():
                continue
            with self.subTest(task=task.task_id):
                # resc is untracked; pass None so only the repl + scenario
                # control/variant lint runs (no Renode/west required).
                validate_renode_case(task, repl_path, None)

    def test_variant_repls_are_copies_of_base_repl(self) -> None:
        for task in _renode_tasks():
            if not task.simulation_variants:
                continue
            case_dir = CASES_DIR / task.case_id
            base_path = case_dir / "case.repl"
            if not base_path.exists():
                continue
            base = base_path.read_text(encoding="utf-8")
            for variant in task.simulation_variants:
                vid = variant_id(variant)
                variant_repl = case_dir / "artifacts" / "variants" / vid / "case.repl"
                if not variant_repl.exists():
                    continue
                with self.subTest(task=task.task_id, variant=vid):
                    self.assertEqual(
                        base,
                        variant_repl.read_text(encoding="utf-8"),
                        f"{variant_repl} diverges from the base case.repl; "
                        f"regenerate `python -m bench.cli generate --task {task.task_id}`",
                    )


if __name__ == "__main__":
    unittest.main()

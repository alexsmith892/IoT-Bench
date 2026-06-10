"""Level-2/level-3 reference sketches are regenerated from the templates in
bench.runner on every `generate`. The committed cases/*/sketch/*.ino are therefore
derived artifacts. This test pins them to the templates so they cannot silently
drift (whether by editing runner.py without regenerating, or by hand-editing a
committed .ino). Level 1 is excluded because its sketches are authored, not
regenerated (ensure_sketch_files only writes them when missing)."""

import tempfile
import unittest
from pathlib import Path

from bench.config import iter_tasks
from bench.runner import case_dir_for_task, generate_case


class ReferenceSketchConsistencyTests(unittest.TestCase):
    def test_committed_level2_3_sketches_match_templates(self):
        mismatches = []
        for level in ("level2", "level3"):
            for task in iter_tasks(platform="arduino_mega", level=level):
                if not task.is_supported:
                    continue  # unsupported/manual tasks are not generated
                committed = (
                    case_dir_for_task(task)
                    / "sketch"
                    / task.sketch_name
                    / f"{task.sketch_name}.ino"
                )
                self.assertTrue(
                    committed.exists(),
                    f"{task.task_id}: committed reference sketch missing at {committed}",
                )
                with tempfile.TemporaryDirectory() as tmp:
                    generated = (
                        generate_case(task, root=Path(tmp)).sketch
                        / f"{task.sketch_name}.ino"
                    )
                    if (
                        generated.read_text(encoding="utf-8")
                        != committed.read_text(encoding="utf-8")
                    ):
                        mismatches.append(task.task_id)
        self.assertEqual(
            mismatches,
            [],
            "committed reference sketch(es) drifted from runner.py templates; "
            f"regenerate them: {mismatches}",
        )


if __name__ == "__main__":
    unittest.main()

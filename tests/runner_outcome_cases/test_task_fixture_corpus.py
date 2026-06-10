from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench.config import iter_tasks
from bench.runner import generate_case, normalize_sketch_override

from tests.runner_outcome_cases.helpers import task_fixture


class PerTaskFixtureCorpusTests(unittest.TestCase):
    def test_every_supported_task_has_good_and_bad_ino_controls(self):
        missing: list[str] = []
        for level in ("level1", "level2", "level3"):
            for task in iter_tasks(platform="arduino_mega", level=level):
                if not task.is_supported:
                    continue
                for outcome in ("good", "bad"):
                    fixture = task_fixture(level, task.task_id, outcome)
                    if not fixture.exists():
                        missing.append(str(fixture))
                        continue
                    text = fixture.read_text(encoding="utf-8")
                    self.assertIn("void setup", text, str(fixture))
                    self.assertIn("void loop", text, str(fixture))

        self.assertEqual(missing, [])

    def test_good_controls_match_committed_reference_sketches(self):
        mismatches: list[str] = []
        for level in ("level1", "level2", "level3"):
            for task in iter_tasks(platform="arduino_mega", level=level):
                if not task.is_supported:
                    continue
                reference = (
                    Path("cases")
                    / task.case_id
                    / "sketch"
                    / task.sketch_name
                    / f"{task.sketch_name}.ino"
                )
                if task_fixture(level, task.task_id, "good").read_text(encoding="utf-8") != reference.read_text(encoding="utf-8"):
                    mismatches.append(task.task_id)

        self.assertEqual(mismatches, [])

    def test_bad_controls_are_distinct_compilable_shape_submissions(self):
        duplicates: list[str] = []
        for level in ("level1", "level2", "level3"):
            for task in iter_tasks(platform="arduino_mega", level=level):
                if not task.is_supported:
                    continue
                good = task_fixture(level, task.task_id, "good").read_text(encoding="utf-8")
                bad = task_fixture(level, task.task_id, "bad").read_text(encoding="utf-8")
                if good == bad:
                    duplicates.append(task.task_id)

        self.assertEqual(duplicates, [])

    def test_runner_accepts_each_task_fixture_as_a_sketch_override(self):
        for level in ("level1", "level2", "level3"):
            for task in iter_tasks(platform="arduino_mega", level=level):
                if not task.is_supported:
                    continue
                with self.subTest(task=task.task_id), tempfile.TemporaryDirectory() as tmp:
                    paths = generate_case(task, root=Path(tmp))
                    for outcome in ("good", "bad"):
                        normalized = normalize_sketch_override(
                            task,
                            paths,
                            task_fixture(level, task.task_id, outcome),
                        )
                        assert normalized is not None
                        self.assertEqual(normalized.name, task.sketch_name)
                        self.assertTrue((normalized / f"{task.sketch_name}.ino").exists())


if __name__ == "__main__":
    unittest.main()

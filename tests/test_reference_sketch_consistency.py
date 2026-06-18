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


EXPECTED_ESPIDF_SOURCE_DRIFT: set[tuple[str, str]] = set()

# The empty stub the generator must never silently emit for a real task.
_EMPTY_STUB = "void setup() {}\nvoid loop() {}\n"


class ReferenceSketchConsistencyTests(unittest.TestCase):
    def test_every_arduino_task_has_a_nontrivial_committed_sketch(self):
        """Every supported arduino_mega task must ship a real committed sketch.

        Level-1 sketches are authored (not regenerated), and a few are absent
        from the runner template tables. Guard against a deleted/empty sketch
        riding the build as an empty `setup/loop` stub: the committed .ino must
        exist and contain actual firmware, not the empty fallback."""
        missing = []
        trivial = []
        for level in ("level1", "level2", "level3"):
            for task in iter_tasks(platform="arduino_mega", level=level):
                if not task.is_supported:
                    continue
                committed = (
                    case_dir_for_task(task)
                    / "sketch"
                    / task.sketch_name
                    / f"{task.sketch_name}.ino"
                )
                if not committed.exists():
                    missing.append(task.task_id)
                    continue
                source = committed.read_text(encoding="utf-8")
                if source.strip() in ("", _EMPTY_STUB.strip()):
                    trivial.append(task.task_id)
        self.assertEqual(missing, [], f"committed Arduino sketch(es) missing: {missing}")
        self.assertEqual(
            trivial, [], f"committed Arduino sketch(es) are empty stubs: {trivial}"
        )


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

    def test_committed_esp32s3_espidf_level2_3_sources_match_templates(self):
        mismatches = []
        for level in ("level2", "level3"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for task in iter_tasks(platform="esp32s3_espidf", level=level):
                    if not task.is_supported:
                        continue
                    committed = (
                        case_dir_for_task(task)
                        / "sketch"
                        / task.sketch_name
                        / "main"
                        / "main.c"
                    )
                    self.assertTrue(
                        committed.exists(),
                        f"{task.task_id}: committed ESP-IDF reference missing at {committed}",
                    )
                    generated = (
                        generate_case(task, root=root).sketch
                        / "main"
                        / "main.c"
                    )
                    task_key = (level, task.task_id)
                    if (
                        generated.read_text(encoding="utf-8")
                        != committed.read_text(encoding="utf-8")
                    ):
                        mismatches.append(task_key)
        unexpected = [
            mismatch for mismatch in mismatches if mismatch not in EXPECTED_ESPIDF_SOURCE_DRIFT
        ]
        self.assertEqual(
            unexpected,
            [],
            "committed ESP32-S3 ESP-IDF reference source(s) drifted from "
            "bench.runner templates; regenerate with explicit "
            "`python -m bench.cli generate --platform esp32s3_espidf --level <level>`: "
            f"{unexpected}",
        )
        self.assertEqual(
            sorted(mismatches),
            sorted(EXPECTED_ESPIDF_SOURCE_DRIFT),
            "expected ESP32 source drift allowlist is stale; update or remove it",
        )


if __name__ == "__main__":
    unittest.main()

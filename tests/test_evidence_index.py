import unittest

from bench.config import iter_platform_tasks
from bench.evidence import build_evidence_index, evidence_stale_reasons


PLATFORM = "esp32s3_espidf"


class EvidenceIndexTests(unittest.TestCase):
    def test_index_covers_every_task(self):
        index = build_evidence_index(PLATFORM)
        task_ids = {entry["task_id"] for entry in index["tasks"]}
        expected = {task.task_id for task in iter_platform_tasks(platform=PLATFORM)}
        self.assertEqual(task_ids, expected)
        self.assertEqual(index["summary"]["total"], len(expected))
        # Summary counts are internally consistent.
        s = index["summary"]
        self.assertEqual(
            s["total"],
            s["present"]
            + s["missing"]
            + sum(
                1
                for e in index["tasks"]
                if e.get("evidence") not in {"present", "missing"}
            ),
        )

    def test_matching_manifest_is_fresh(self):
        manifest = {
            "task_hash": "aaa",
            "prompt_hash": "bbb",
            "sketch_hash": "ccc",
            "idf_py_version": "ESP-IDF v5.5.4",
            "wokwi_cli_version": "0.26.1",
        }
        current = {"task_hash": "aaa", "prompt_hash": "bbb", "sketch_hash": "ccc"}
        pinned = {"idf_py_version": "ESP-IDF v5.5.4", "wokwi_cli_version": "0.26.1"}
        self.assertEqual(
            evidence_stale_reasons(manifest, current=current, pinned=pinned, build_kind="espidf"),
            [],
        )

    def test_mutated_input_hash_flags_stale(self):
        manifest = {"task_hash": "aaa", "prompt_hash": "bbb", "sketch_hash": "ccc"}
        current = {"task_hash": "MUTATED", "prompt_hash": "bbb", "sketch_hash": "ccc"}
        reasons = evidence_stale_reasons(manifest, current=current, pinned={}, build_kind="espidf")
        self.assertIn("task_hash", reasons)

    def test_tool_version_drift_flags_stale(self):
        manifest = {
            "task_hash": "aaa",
            "prompt_hash": "bbb",
            "sketch_hash": "ccc",
            "idf_py_version": "ESP-IDF v5.4.0",
        }
        current = {"task_hash": "aaa", "prompt_hash": "bbb", "sketch_hash": "ccc"}
        pinned = {"idf_py_version": "ESP-IDF v5.5.4", "wokwi_cli_version": None}
        reasons = evidence_stale_reasons(manifest, current=current, pinned=pinned, build_kind="espidf")
        self.assertIn("tool:idf.py", reasons)

    def test_unset_pinned_version_is_not_a_stale_reason(self):
        manifest = {"task_hash": "aaa", "prompt_hash": "bbb", "sketch_hash": "ccc"}
        current = {"task_hash": "aaa", "prompt_hash": "bbb", "sketch_hash": "ccc"}
        # No pinned versions: a missing pin should not flag tool drift.
        self.assertEqual(
            evidence_stale_reasons(manifest, current=current, pinned={}, build_kind="espidf"),
            [],
        )


if __name__ == "__main__":
    unittest.main()

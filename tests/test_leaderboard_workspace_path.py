"""The per-attempt build workspace must use a short directory segment.

Regression guard for a live-test finding: the case tree generated under the
workspace is deep (cases/<case_id>/artifacts/submissions/<sketch_name>/main/...),
and on Windows a verbose "<task>.<mode>.<rep>" segment pushed the longest-named
ESP-IDF tasks past MAX_PATH (260) during submission extraction and artifact
copy-back, producing spurious IF results. The workspace segment must stay short
(a hash), distinct per attempt, and stable across if-retries.
"""

import unittest
from pathlib import Path

from bench.leaderboard.evaluate import _workspace_dir


class WorkspacePathTests(unittest.TestCase):
    def test_segment_is_short_regardless_of_slug_length(self):
        long_slug = "lcd1602_auto_brightness_control.human_expert.3"
        ws = _workspace_dir(Path("runs/r"), long_slug, 1)
        self.assertLessEqual(len(ws.parent.name), 12)
        self.assertEqual(ws.name, "if_1")
        self.assertEqual(ws.parent.parent.name, "workspace")

    def test_distinct_slugs_get_distinct_dirs(self):
        a = _workspace_dir(Path("runs/r"), "task_a.none.1", 1)
        b = _workspace_dir(Path("runs/r"), "task_b.none.1", 1)
        self.assertNotEqual(a.parent.name, b.parent.name)

    def test_same_slug_stable_across_calls_but_if_index_varies(self):
        s = "task_a.none.1"
        self.assertEqual(_workspace_dir(Path("runs/r"), s, 1), _workspace_dir(Path("runs/r"), s, 1))
        self.assertEqual(_workspace_dir(Path("runs/r"), s, 1).parent, _workspace_dir(Path("runs/r"), s, 2).parent)
        self.assertNotEqual(_workspace_dir(Path("runs/r"), s, 1), _workspace_dir(Path("runs/r"), s, 2))


if __name__ == "__main__":
    unittest.main()

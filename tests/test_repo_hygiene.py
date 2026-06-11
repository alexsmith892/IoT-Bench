"""Generated outputs must never be tracked in git (fixtures are allowlisted)."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Tracked paths under cases/*/artifacts/ must match one of these patterns.
# Variant diagram.json files are deterministic derived inputs consumed by the
# provenance manifest and --use-existing-artifacts validation, so they are
# deliberately committed (see .gitignore).
ALLOWED_CASE_ARTIFACTS = [
    re.compile(r"^cases/[^/]+/artifacts/variants/[^/]+/diagram\.json$"),
]

# Generated-output file kinds that must never be tracked anywhere outside
# explicit test fixtures.
FORBIDDEN_PATTERNS = [
    re.compile(r"\.vcd$"),
    re.compile(r"\.serial\.log$"),
    re.compile(r"(^|/)verification\.json$"),
    re.compile(r"\.ino\.(hex|elf|eep|bin)$"),
    re.compile(r"\.ino\.with_bootloader\."),
]


def tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise unittest.SkipTest("git is not available or this is not a work tree")
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


class RepoHygieneTests(unittest.TestCase):
    def test_no_generated_outputs_tracked_under_case_artifacts(self):
        offenders = [
            path
            for path in tracked_files()
            if re.match(r"^cases/[^/]+/artifacts/", path)
            and not any(pattern.match(path) for pattern in ALLOWED_CASE_ARTIFACTS)
        ]
        self.assertEqual(offenders, [], "untrack generated case artifacts (git rm --cached)")

    def test_no_forbidden_output_kinds_tracked(self):
        offenders = [
            path
            for path in tracked_files()
            if not path.startswith("tests/fixtures/")
            and any(pattern.search(path) for pattern in FORBIDDEN_PATTERNS)
        ]
        self.assertEqual(offenders, [], "generated output files must not be tracked")

    def test_root_diagram_fixture_exists(self):
        self.assertTrue((ROOT / "tests" / "fixtures" / "diagram.json").exists())


if __name__ == "__main__":
    unittest.main()

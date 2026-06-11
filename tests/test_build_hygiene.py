"""Build isolation: stale or wrong-stem firmware must never satisfy a build."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.cli import build_single_task
from bench.config import load_task
from bench.results import RESULT_IF
from bench.runner import (
    BuildSimulationError,
    CaseConfigError,
    CasePaths,
    clean_build_dir,
    ensure_firmware_outputs,
    generate_case,
)


def synthetic_paths(case_dir: Path, *, build_dir: Path | None = None) -> CasePaths:
    return CasePaths(
        task_id="task",
        case_id="case",
        case_dir=case_dir,
        sketch=case_dir / "sketch" / "blink",
        diagram=case_dir / "diagram.json",
        wokwi_toml=case_dir / "wokwi.toml",
        build_dir=build_dir or (case_dir / "artifacts" / "build"),
        fqbn="arduino:avr:mega",
    )


class BuildHygieneTests(unittest.TestCase):
    def test_stale_firmware_in_build_dir_yields_if_when_compile_produces_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = load_task("blink_led_1hz")
            paths = generate_case(task, root=root)

            # Stale firmware from a previous build at the expected locations.
            firmware_hex, firmware_elf = paths.firmware_hex, paths.firmware_elf
            firmware_hex.parent.mkdir(parents=True, exist_ok=True)
            firmware_hex.write_bytes(b"stale hex")
            firmware_elf.write_bytes(b"stale elf")

            with patch("bench.runner.run_checked", return_value=None):
                payload = build_single_task(
                    task,
                    case_dir=paths.case_dir,
                    sketch_override=None,
                    regenerate=False,
                    arduino_cli="arduino-cli",
                )

        self.assertEqual(payload["result"], RESULT_IF, payload)

    def test_wrong_stem_firmware_is_not_normalized_into_expected_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            paths = synthetic_paths(case_dir)
            paths.build_dir.mkdir(parents=True)
            (paths.build_dir / "other.ino.hex").write_bytes(b"hex")
            (paths.build_dir / "other.ino.elf").write_bytes(b"elf")

            with self.assertRaises(BuildSimulationError) as ctx:
                ensure_firmware_outputs(paths)

        self.assertEqual(ctx.exception.classification, "SIM_OUTPUT_FAIL")
        self.assertFalse((case_dir / "artifacts" / "build" / "blink.ino.hex").exists())

    def test_firmware_outside_build_dir_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            paths = synthetic_paths(case_dir)
            paths.build_dir.mkdir(parents=True)
            sketch_dir = paths.sketch
            sketch_dir.mkdir(parents=True)
            (sketch_dir / "blink.ino.hex").write_bytes(b"hex")
            (sketch_dir / "blink.ino.elf").write_bytes(b"elf")

            with self.assertRaises(BuildSimulationError):
                ensure_firmware_outputs(paths)

    def test_matching_firmware_in_build_subdir_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            paths = synthetic_paths(case_dir)
            nested = paths.build_dir / "nested"
            nested.mkdir(parents=True)
            (nested / "blink.ino.hex").write_bytes(b"hex")
            (nested / "blink.ino.elf").write_bytes(b"elf")

            ensure_firmware_outputs(paths)

        # No exception: exact-stem binaries inside the build dir are accepted.

    def test_clean_build_dir_removes_previous_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            paths = synthetic_paths(case_dir)
            paths.build_dir.mkdir(parents=True)
            stale = paths.build_dir / "blink.ino.hex"
            stale.write_bytes(b"stale")

            clean_build_dir(paths)

            self.assertTrue(paths.build_dir.exists())
            self.assertFalse(stale.exists())

    def test_clean_build_dir_refuses_paths_escaping_the_case_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_dir = root / "case"
            case_dir.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "keep.txt").write_text("keep", encoding="utf-8")
            paths = synthetic_paths(case_dir, build_dir=outside)

            with self.assertRaises(CaseConfigError):
                clean_build_dir(paths)

            self.assertTrue((outside / "keep.txt").exists())

    def test_clean_build_dir_refuses_the_case_dir_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "case"
            case_dir.mkdir()
            paths = synthetic_paths(case_dir, build_dir=case_dir)

            with self.assertRaises(CaseConfigError):
                clean_build_dir(paths)

            self.assertTrue(case_dir.exists())


if __name__ == "__main__":
    unittest.main()

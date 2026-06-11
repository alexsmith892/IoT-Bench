import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.config import load_task
from bench.runner import (
    BuildSimulationError,
    CasePaths,
    archive_current_outputs,
    ensure_existing_outputs,
    load_case_paths,
    resolve_archived_vcd,
    simulate_case,
    with_archived_vcd,
)

def make_paths(case_dir: Path, vcd: Path | None = None) -> CasePaths:
    return CasePaths(
        task_id="blink_led_1hz",
        case_id=case_dir.name,
        sketch=case_dir / "sketch" / "blink" / "blink.ino",
        diagram=case_dir / "diagram.json",
        vcd=vcd or case_dir / "artifacts" / "logic" / "wokwi.vcd",
        case_dir=case_dir,
        build_dir=case_dir / "artifacts" / "build",
        wokwi_toml=case_dir / "wokwi.toml",
        fqbn="arduino:avr:mega",
    )


class WokwiCaseRunnerTests(unittest.TestCase):
    def test_archive_existing_vcd_moves_current_vcd_into_case_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "blink-1hz-wokwi-mega"
            paths = make_paths(case_dir)
            assert paths.vcd is not None
            paths.vcd.parent.mkdir(parents=True)
            paths.vcd.write_text("old vcd\n", encoding="utf-8")

            archive_current_outputs(paths)

            archived_files = list((case_dir / "artifacts" / "archive" / "vcd").glob("*.vcd"))
            self.assertEqual(len(archived_files), 1)
            archived = archived_files[0]
            self.assertFalse(paths.vcd.exists())
            self.assertEqual(archived.read_text(encoding="utf-8"), "old vcd\n")
            self.assertEqual(
                archived.parent,
                case_dir / "artifacts" / "archive" / "vcd",
            )
            self.assertRegex(
                archived.name,
                (
                    r"^blink-1hz-wokwi-mega__\d{8}T\d{12}Z__"
                    r"wokwi\.vcd$"
                ),
            )

    def test_failed_simulation_cannot_leave_stale_outputs_for_validation(self):
        # archive_current_outputs runs before wokwi launches, so a failed
        # simulation must leave no current VCD that a later validation could
        # mistake for fresh output.
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "blink-1hz-wokwi-mega"
            paths = make_paths(case_dir)
            assert paths.vcd is not None
            paths.vcd.parent.mkdir(parents=True)
            paths.vcd.write_text("stale vcd\n", encoding="utf-8")
            (case_dir / "diagram.json").write_text("{}", encoding="utf-8")
            (case_dir / "wokwi.toml").write_text("[wokwi]\nversion = 1\n", encoding="utf-8")
            paths.firmware_hex.parent.mkdir(parents=True, exist_ok=True)
            paths.firmware_hex.write_bytes(b"hex")
            paths.firmware_elf.write_bytes(b"elf")
            task = load_task("blink_led_1hz")

            sim_error = BuildSimulationError(
                "wokwi crashed",
                classification="SIM_INFRA_FAIL",
                failure_stage="simulate",
                failure_source="simulator",
            )
            with patch("bench.runner.run_checked", side_effect=sim_error):
                with self.assertRaises(BuildSimulationError):
                    simulate_case(task, paths)

            self.assertFalse(paths.vcd.exists(), "stale VCD must have been archived away")
            archived = list((case_dir / "artifacts" / "archive" / "vcd").glob("*.vcd"))
            self.assertEqual(len(archived), 1)
            with self.assertRaises(BuildSimulationError) as ctx:
                ensure_existing_outputs(task, paths)
            self.assertEqual(ctx.exception.classification, "SIM_OUTPUT_FAIL")

    def test_resolve_archived_vcd_accepts_filename_and_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "blink-led-no-delay-wokwi-mega"
            paths = make_paths(case_dir)
            archive_dir = case_dir / "artifacts" / "archive" / "vcd"
            archive_dir.mkdir(parents=True)
            older = archive_dir / "blink-led-no-delay-wokwi-mega__20260608T100000000000Z__wokwi.vcd"
            newer = archive_dir / "blink-led-no-delay-wokwi-mega__20260608T110000000000Z__wokwi.vcd"
            older.write_text("older\n", encoding="utf-8")
            newer.write_text("newer\n", encoding="utf-8")

            self.assertEqual(resolve_archived_vcd(paths, older.name), older)
            self.assertEqual(resolve_archived_vcd(paths, "latest"), newer)

    def test_load_case_paths_can_use_archived_vcd_for_a_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "breathing-led-wokwi-mega"
            archive_dir = case_dir / "artifacts" / "archive" / "vcd"
            archive_dir.mkdir(parents=True)
            archived = archive_dir / "breathing-led-wokwi-mega__20260608T110000000000Z__wokwi.vcd"
            archived.write_text("archived\n", encoding="utf-8")
            (case_dir / "case.yaml").write_text(
                (
                    "task_id: breathing_led\n"
                    "case_id: breathing-led-wokwi-mega\n"
                    "board:\n"
                    "  fqbn: arduino:avr:mega\n"
                    "paths:\n"
                    "  sketch: sketch/breathing\n"
                    "  diagram: diagram.json\n"
                    "  wokwi: wokwi.toml\n"
                    "  build: artifacts/build\n"
                    "  vcd: artifacts/logic/wokwi.vcd\n"
                ),
                encoding="utf-8",
            )

            task = load_task("breathing_led")
            paths = with_archived_vcd(load_case_paths(task, case_dir), "latest")

            self.assertEqual(paths.vcd, archived)


if __name__ == "__main__":
    unittest.main()

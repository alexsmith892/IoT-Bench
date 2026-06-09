import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wokwi_case_runner import (  # noqa: E402
    WokwiCaseConfig,
    archive_existing_vcd,
    resolve_archived_vcd,
    resolve_runner_config,
)


def make_config(case_dir: Path, vcd: Path | None = None) -> WokwiCaseConfig:
    return WokwiCaseConfig(
        sketch=case_dir / "sketch" / "blink" / "blink.ino",
        diagram=case_dir / "diagram.json",
        vcd=vcd or case_dir / "artifacts" / "logic" / "wokwi.vcd",
        case_dir=case_dir,
        build_dir=case_dir / "artifacts" / "build",
        wokwi_toml=case_dir / "wokwi.toml",
        fqbn="arduino:avr:mega",
        signal_name="D0",
        expected_pin="3",
    )


class WokwiCaseRunnerTests(unittest.TestCase):
    def test_archive_existing_vcd_moves_current_vcd_into_case_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "blink-1hz-wokwi-mega"
            config = make_config(case_dir)
            config.vcd.parent.mkdir(parents=True)
            config.vcd.write_text("old vcd\n", encoding="utf-8")

            archived = archive_existing_vcd(config)

            self.assertIsNotNone(archived)
            assert archived is not None
            self.assertFalse(config.vcd.exists())
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

    def test_resolve_archived_vcd_accepts_filename_and_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "blink-led-no-delay-wokwi-mega"
            config = make_config(case_dir)
            archive_dir = case_dir / "artifacts" / "archive" / "vcd"
            archive_dir.mkdir(parents=True)
            older = archive_dir / "blink-led-no-delay-wokwi-mega__20260608T100000000000Z__wokwi.vcd"
            newer = archive_dir / "blink-led-no-delay-wokwi-mega__20260608T110000000000Z__wokwi.vcd"
            older.write_text("older\n", encoding="utf-8")
            newer.write_text("newer\n", encoding="utf-8")

            self.assertEqual(resolve_archived_vcd(config, older.name), older)
            self.assertEqual(resolve_archived_vcd(config, "latest"), newer)

    def test_resolve_runner_config_can_use_archived_vcd_for_a_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "breathing-led-wokwi-mega"
            archive_dir = case_dir / "artifacts" / "archive" / "vcd"
            archive_dir.mkdir(parents=True)
            archived = archive_dir / "breathing-led-wokwi-mega__20260608T110000000000Z__wokwi.vcd"
            archived.write_text("archived\n", encoding="utf-8")
            (case_dir / "case.json").write_text(
                (
                    '{"paths":{"sketch":"sketch/breathing","diagram":"diagram.json",'
                    '"vcd":"artifacts/logic/wokwi.vcd"}}'
                ),
                encoding="utf-8",
            )

            config = resolve_runner_config(
                Namespace(
                    case=case_dir,
                    sketch=None,
                    diagram=None,
                    vcd=None,
                    archived_vcd="latest",
                ),
                case_dir,
            )

            self.assertEqual(config.vcd, archived)


if __name__ == "__main__":
    unittest.main()

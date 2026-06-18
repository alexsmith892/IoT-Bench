"""Empty required serial output after a clean sim is a behavioral FAIL, not IF.

Regression guard for the leaderboard finding: a submission that compiles and
simulates cleanly but prints nothing produced a 0-byte serial log, which used to
be classified SIM_OUTPUT_FAIL -> IF (a free pass excluded from scoring). After a
successful simulation it must be charged to the firmware as a behavioral FAIL.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bench.runner import BuildSimulationError, ensure_existing_outputs
from bench.results import (
    FAIL,
    SIM_OUTPUT_FAIL,
    SOURCE_ARTIFACT,
    SOURCE_USER_CODE,
    STAGE_BEHAVIOR,
    STAGE_SIM_OUTPUT,
)


def _task():
    return SimpleNamespace(requires_serial_log=True, requires_vcd=False)


def _paths(serial_log):
    return SimpleNamespace(serial_log=serial_log, vcd=None)


class EmptyOutputClassificationTests(unittest.TestCase):
    def test_empty_serial_after_clean_sim_is_behavior_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "serial.log"
            log.write_bytes(b"")  # firmware ran but printed nothing
            with self.assertRaises(BuildSimulationError) as cm:
                ensure_existing_outputs(_task(), _paths(log), empty_is_behavior=True)
            self.assertEqual(cm.exception.classification, FAIL)
            self.assertEqual(cm.exception.failure_stage, STAGE_BEHAVIOR)
            self.assertEqual(cm.exception.failure_source, SOURCE_USER_CODE)

    def test_empty_serial_for_existing_artifacts_stays_output_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "serial.log"
            log.write_bytes(b"")
            with self.assertRaises(BuildSimulationError) as cm:
                ensure_existing_outputs(_task(), _paths(log))  # default: not fresh
            self.assertEqual(cm.exception.classification, SIM_OUTPUT_FAIL)
            self.assertEqual(cm.exception.failure_source, SOURCE_ARTIFACT)

    def test_missing_serial_stays_output_fail_even_after_sim(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "absent.log"  # never created -> sim/infra problem
            with self.assertRaises(BuildSimulationError) as cm:
                ensure_existing_outputs(_task(), _paths(log), empty_is_behavior=True)
            self.assertEqual(cm.exception.classification, SIM_OUTPUT_FAIL)
            self.assertEqual(cm.exception.failure_stage, STAGE_SIM_OUTPUT)

    def test_nonempty_serial_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "serial.log"
            log.write_bytes(b"Humidity: 40%\n")
            ensure_existing_outputs(_task(), _paths(log), empty_is_behavior=True)  # no raise


if __name__ == "__main__":
    unittest.main()

"""Positive (anti-over-fit) guard for ESP32-S3 serial oracles.

``tests.test_espidf_decoy_runtime`` pins that *cheating* captures FAIL. This
module pins the complementary invariant: a correct submission whose output
merely *conforms to the prompt's stated contract* — but is worded differently
from the committed reference — still PASSes. That guards against an oracle that
silently over-fits to the reference's exact byte stream and would false-BF an
equally-correct independent implementation.

Scope: serial oracles only, where a conforming capture can be authored by hand.
Synthesizing a *passing* LCD/VCD capture (a valid 4-bit bus frame or a precise
waveform) is impractical to do reliably offline, so display/waveform tasks rely
on the live reference run plus the negative decoy guard instead. Extending this
table to more serial tasks is cheap; the two below cover the format-contract
disclosures most at risk of over-fit (the rotary direction/position line and the
DHT temperature/humidity line).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench.config import load_task
from bench.runner import generate_case

from tests.runner_outcome_cases.helpers import write_multi_vcd
from tests.validator_test_utils import assert_classification, validate_artifacts_args


# (task_id, level, serial_text). Each serial_text is deliberately NOT the
# committed reference wording, yet satisfies the prompt's stated output contract.
POSITIVE_SERIAL_CASES = [
    (
        "rotary_encoder",
        "level2",
        # Reference prints "Position: <n> Direction: CW"; this uses different
        # surrounding text and extra tokens but still carries the mandated
        # "Direction: CW/CCW" label with the running integer position.
        "\n".join(
            [
                "[boot] quadrature encoder ready",
                "detent -> Direction: CW, now at position 1",
                "detent -> Direction: CW, now at position 2",
                "detent -> Direction: CW, now at position 3",
                "detent -> Direction: CCW, now at position 2",
                "detent -> Direction: CCW, now at position 1",
            ]
        )
        + "\n",
    ),
    (
        "dht11_read",
        "level2",
        # Reference prints "Temp: 18 C  Hum: 35 %"; this rewords the labels and
        # punctuation while keeping Temp/Hum + in-range values on one line each.
        "\n".join(
            [
                "DHT11 sensor warm-up complete",
                "cool/dry reading -> Temperature 18 C / Humidity 35 %",
                "warm/humid reading -> Temperature 31 C / Humidity 65 %",
            ]
        )
        + "\n",
    ),
]


class EspIdfPositiveOverfitTests(unittest.TestCase):
    def test_conforming_but_diverse_serial_output_passes(self):
        for task_id, level, serial_text in POSITIVE_SERIAL_CASES:
            with self.subTest(task=task_id):
                self._assert_passes(task_id, level, serial_text)

    def _assert_passes(self, task_id: str, level: str, serial_text: str) -> None:
        task = load_task(task_id, platform="esp32s3_espidf", level=level)
        self.assertFalse(
            task.simulation_variants,
            f"{task_id}: positive guard assumes a single-scenario task",
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = generate_case(task, root=Path(tmp))
            self.assertIsNotNone(
                paths.serial_log, f"{task_id}: expected a serial artifact"
            )
            paths.serial_log.parent.mkdir(parents=True, exist_ok=True)
            paths.serial_log.write_text(serial_text, encoding="utf-8")
            # Fill any co-declared VCD with a parseable placeholder so the
            # artifact-existence pre-check does not return IF; the serial oracle
            # is what decides PASS here.
            if paths.vcd is not None:
                write_multi_vcd(paths.vcd, {"D0": [(0, 0), (0.001, 1), (0.002, 0)]})

            assert_classification(
                self,
                validate_artifacts_args(task_id, paths.case_dir)
                + ["--platform", "esp32s3_espidf", "--level", level],
                "PASS",
            )


if __name__ == "__main__":
    unittest.main()

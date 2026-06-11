"""LCD decode behavior must be unchanged by the bisect-based signal readers."""

from __future__ import annotations

import random
import unittest

from bench.lcd1602 import value_at
from bench.vcd import VcdEvent


def linear_value_at(events: list[VcdEvent], time_s: float) -> int:
    # Reference copy of the historical linear implementation.
    value = events[0].value if events else 0
    for event in events:
        if event.timestamp_s > time_s:
            break
        value = event.value
    return value


class ValueAtEquivalenceTests(unittest.TestCase):
    def test_empty_events(self):
        self.assertEqual(value_at([], 1.0), 0)

    def test_probe_before_first_event_returns_first_value(self):
        events = [VcdEvent(1.0, 1), VcdEvent(2.0, 0)]
        self.assertEqual(value_at(events, 0.5), 1)
        self.assertEqual(value_at(events, 0.5), linear_value_at(events, 0.5))

    def test_exact_timestamp_probe(self):
        events = [VcdEvent(1.0, 1), VcdEvent(2.0, 0)]
        self.assertEqual(value_at(events, 1.0), linear_value_at(events, 1.0))
        self.assertEqual(value_at(events, 2.0), linear_value_at(events, 2.0))

    def test_randomized_equivalence(self):
        rng = random.Random(20260610)
        for _trial in range(50):
            timestamps = sorted(rng.uniform(0, 10) for _ in range(rng.randint(1, 40)))
            events = [VcdEvent(stamp, rng.randint(0, 1)) for stamp in timestamps]
            probes = [rng.uniform(-1, 11) for _ in range(25)] + [event.timestamp_s for event in events]
            for probe in probes:
                self.assertEqual(
                    value_at(events, probe),
                    linear_value_at(events, probe),
                    (events, probe),
                )


if __name__ == "__main__":
    unittest.main()

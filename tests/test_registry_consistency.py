"""Guards against drift between the declared family sets in bench.config and the
dispatch tables that implement them. Adding a fixture/validator/scenario family
in one place but not the others is a common scaling mistake that otherwise only
surfaces as a confusing runtime error; this turns it into a load-time test failure."""

import unittest

from bench.config import FIXTURE_FAMILIES, SCENARIO_FAMILIES, VALIDATOR_FAMILIES
from bench.diagrams import FIXTURE_GENERATORS
from bench.scenarios import SCENARIO_GENERATORS
from bench.validators import COMPOSITE_CHECK_VALIDATORS, VALIDATORS


class RegistryConsistencyTests(unittest.TestCase):
    def test_fixture_families_match_diagram_generators(self):
        self.assertEqual(FIXTURE_FAMILIES, set(FIXTURE_GENERATORS))

    def test_validator_families_match_validator_dispatch(self):
        self.assertEqual(VALIDATOR_FAMILIES, set(VALIDATORS))

    def test_scenario_families_match_scenario_generators(self):
        self.assertEqual(SCENARIO_FAMILIES, set(SCENARIO_GENERATORS))

    def test_composite_check_validators_are_a_subset_of_validators(self):
        # Composite sub-checks must be real validator families, and must exclude
        # families that cannot be composed (composite itself + whole-trace
        # waveform families).
        self.assertTrue(set(COMPOSITE_CHECK_VALIDATORS).issubset(set(VALIDATORS)))
        non_composable = {
            "composite",
            "morse_sos",
            "no_delay_static_plus_waveform",
            "pwm_breathing",
        }
        self.assertEqual(
            set(VALIDATORS) - set(COMPOSITE_CHECK_VALIDATORS),
            non_composable,
        )


if __name__ == "__main__":
    unittest.main()

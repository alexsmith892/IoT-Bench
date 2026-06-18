import unittest
from unittest.mock import patch

from bench.leaderboard.tokenization import split_token_counts


class _FakeEncoder:
    name = "fake/test"

    def encode(self, text):
        # Deterministic, dependency-free: one "token" per whitespace word.
        return text.split()


class LeaderboardTokenizationTests(unittest.TestCase):
    def test_injected_encoder_counts_segments(self):
        base_tokens, skill_tokens, label = split_token_counts(
            "blink the led", "skill: gpio basics here", encoder=_FakeEncoder()
        )
        self.assertEqual(base_tokens, 3)
        self.assertEqual(skill_tokens, 4)
        self.assertEqual(label, "fake/test")

    def test_no_tokenizer_returns_none_not_estimate(self):
        with patch("bench.leaderboard.tokenization._get_encoder", return_value=None):
            self.assertEqual(split_token_counts("a b", "c d e"), (None, None, None))

    def test_empty_skill_block_is_zero_tokens(self):
        base_tokens, skill_tokens, _ = split_token_counts(
            "one two", "", encoder=_FakeEncoder()
        )
        self.assertEqual(base_tokens, 2)
        self.assertEqual(skill_tokens, 0)


if __name__ == "__main__":
    unittest.main()

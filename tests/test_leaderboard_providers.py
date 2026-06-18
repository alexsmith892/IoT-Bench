import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bench.config import ConfigError
from bench.leaderboard.providers import generate_response


def _fake_openai_body():
    return {
        "choices": [{"message": {"content": "void setup(){}\nvoid loop(){}\n"}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


class _FakeHTTPResponse:
    """Minimal stand-in for the object urlopen returns as a context manager."""

    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._buf.read()


class LeaderboardProviderTests(unittest.TestCase):
    def _call(self, model, *, env=None, **kwargs):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeHTTPResponse(_fake_openai_body())

        task = SimpleNamespace()
        with patch("bench.leaderboard.providers.os.environ", env or {}), patch(
            "bench.leaderboard.providers.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            response = generate_response(model, prompt="do it", task=task, **kwargs)
        return response, captured

    def _auth_header(self, headers):
        # urllib title-cases header keys (Authorization -> Authorization).
        for key, value in headers.items():
            if key.lower() == "authorization":
                return value
        return None

    def test_gemini_uses_gemini_endpoint_and_auth(self):
        response, captured = self._call(
            "gemini:gemini-2.5-flash", env={"GEMINI_API_KEY": "g-key"}
        )
        self.assertEqual(
            captured["url"],
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        self.assertEqual(self._auth_header(captured["headers"]), "Bearer g-key")
        self.assertEqual(captured["body"]["model"], "gemini-2.5-flash")
        self.assertEqual(response.usage["input_tokens"], 11)
        self.assertEqual(response.usage["output_tokens"], 7)

    def test_local_is_keyless_and_omits_authorization(self):
        response, captured = self._call("local:llama3", env={})
        self.assertEqual(captured["url"], "http://localhost:11434/v1/chat/completions")
        self.assertIsNone(self._auth_header(captured["headers"]))
        self.assertEqual(captured["body"]["model"], "llama3")
        self.assertEqual(response.text.strip().splitlines()[0], "void setup(){}")

    def test_openrouter_endpoint_auth_and_model_id(self):
        _, captured = self._call(
            "openrouter:openai/gpt-4o-mini", env={"OPENROUTER_API_KEY": "or-key"}
        )
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(self._auth_header(captured["headers"]), "Bearer or-key")
        # The slash-style provider/model id is forwarded verbatim.
        self.assertEqual(captured["body"]["model"], "openai/gpt-4o-mini")

    def test_openrouter_free_model_suffix_preserved(self):
        # `:free` after the first colon must survive prefix parsing.
        _, captured = self._call(
            "openrouter:meta-llama/llama-3.1-8b-instruct:free",
            env={"OPENROUTER_API_KEY": "or-key"},
        )
        self.assertEqual(captured["body"]["model"], "meta-llama/llama-3.1-8b-instruct:free")

    def test_openai_defaults_remain(self):
        _, captured = self._call("openai:gpt-4o-mini", env={"OPENAI_API_KEY": "o-key"})
        self.assertEqual(captured["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(self._auth_header(captured["headers"]), "Bearer o-key")

    def test_required_key_missing_raises(self):
        with self.assertRaises(ConfigError):
            self._call("gemini:gemini-2.5-flash", env={})

    def test_api_base_override_wins(self):
        _, captured = self._call(
            "gemini:gemini-2.5-flash",
            env={"GEMINI_API_KEY": "g-key"},
            api_base="http://localhost:8000/v1",
        )
        self.assertEqual(captured["url"], "http://localhost:8000/v1/chat/completions")

    def test_explicit_api_key_env_overrides_default(self):
        _, captured = self._call(
            "gemini:gemini-2.5-flash",
            env={"MY_KEY": "custom"},
            api_key_env="MY_KEY",
        )
        self.assertEqual(self._auth_header(captured["headers"]), "Bearer custom")

    def test_unknown_provider_rejected(self):
        with self.assertRaises(ConfigError):
            self._call("anthropic:claude", env={"ANTHROPIC_API_KEY": "x"})

    def test_openrouter_style_usage_metadata_is_normalized(self):
        body = {
            "choices": [{"message": {"content": "void setup(){}\nvoid loop(){}\n"}}],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 350,
                "total_tokens": 1550,
                "cost": 0.0,
                "prompt_tokens_details": {"cached_tokens": 128},
                "completion_tokens_details": {"reasoning_tokens": 210},
            },
        }

        def fake_urlopen(request, timeout=None):
            return _FakeHTTPResponse(body)

        with patch("bench.leaderboard.providers.os.environ", {"OPENROUTER_API_KEY": "k"}), patch(
            "bench.leaderboard.providers.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            resp = generate_response(
                "openrouter:qwen/qwen3-coder:free", prompt="x", task=SimpleNamespace()
            )
        u = resp.usage
        self.assertEqual(u["input_tokens"], 1200)
        self.assertEqual(u["output_tokens"], 350)
        self.assertEqual(u["total_tokens"], 1550)
        self.assertEqual(u["reasoning_tokens"], 210)
        self.assertEqual(u["cached_input_tokens"], 128)
        self.assertEqual(u["cost"], 0.0)
        self.assertEqual(u["usage_source"], "provider")


if __name__ == "__main__":
    unittest.main()

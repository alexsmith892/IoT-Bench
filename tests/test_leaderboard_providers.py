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

    def test_anthropic_messages_api_shape_and_usage(self):
        body = {
            "content": [{"type": "text", "text": "void setup(){}\nvoid loop(){}\n"}],
            "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 12},
        }
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeHTTPResponse(body)

        with patch("bench.leaderboard.providers.os.environ", {"ANTHROPIC_API_KEY": "a-key"}), patch(
            "bench.leaderboard.providers.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            resp = generate_response(
                "anthropic:claude-opus-4-8", prompt="do it", task=SimpleNamespace()
            )
        self.assertEqual(captured["url"], "https://api.anthropic.com/v1/messages")
        hdrs = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(hdrs.get("x-api-key"), "a-key")
        self.assertEqual(hdrs.get("anthropic-version"), "2023-06-01")
        self.assertIn("system", captured["body"])
        self.assertIn("max_tokens", captured["body"])
        self.assertEqual(resp.text.splitlines()[0], "void setup(){}")
        self.assertEqual(resp.usage["input_tokens"], 100)
        self.assertEqual(resp.usage["output_tokens"], 50)
        self.assertEqual(resp.usage["total_tokens"], 150)
        self.assertEqual(resp.usage["cached_input_tokens"], 12)
        self.assertEqual(resp.usage["usage_source"], "provider")

    def test_anthropic_requires_key(self):
        with patch("bench.leaderboard.providers.os.environ", {}):
            with self.assertRaises(ConfigError):
                generate_response("anthropic:claude-opus-4-8", prompt="x", task=SimpleNamespace())

    def test_unknown_provider_rejected(self):
        with self.assertRaises(ConfigError):
            self._call("cohere:command", env={"COHERE_API_KEY": "x"})

    def test_openai_new_family_uses_max_completion_tokens_no_sampling(self):
        _, captured = self._call("openai:gpt-5", env={"OPENAI_API_KEY": "k"})
        body = captured["body"]
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("temperature", body)
        self.assertNotIn("top_p", body)

    def test_openai_o_series_uses_new_family_params(self):
        _, captured = self._call("openai:o3-mini", env={"OPENAI_API_KEY": "k"})
        self.assertIn("max_completion_tokens", captured["body"])
        self.assertNotIn("max_tokens", captured["body"])

    def test_openai_legacy_family_keeps_max_tokens_and_sampling(self):
        _, captured = self._call("openai:gpt-4o-mini", env={"OPENAI_API_KEY": "k"})
        body = captured["body"]
        self.assertIn("max_tokens", body)
        self.assertNotIn("max_completion_tokens", body)
        self.assertIn("temperature", body)

    def test_new_family_name_via_openrouter_stays_legacy(self):
        # Aggregators accept legacy params; only direct openai: adjusts.
        _, captured = self._call("openrouter:openai/gpt-5", env={"OPENROUTER_API_KEY": "k"})
        self.assertIn("max_tokens", captured["body"])
        self.assertNotIn("max_completion_tokens", captured["body"])

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


class ProviderRetryPolicyTests(unittest.TestCase):
    def test_default_and_env_override_and_invalid(self):
        from bench.leaderboard import providers

        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(providers._provider_max_attempts(), providers.DEFAULT_MAX_ATTEMPTS)
        with patch.dict("os.environ", {"IOTBENCH_PROVIDER_MAX_ATTEMPTS": "9"}, clear=True):
            self.assertEqual(providers._provider_max_attempts(), 9)
        for bad in ("0", "-2", "abc"):
            with patch.dict("os.environ", {"IOTBENCH_PROVIDER_MAX_ATTEMPTS": bad}, clear=True):
                self.assertEqual(providers._provider_max_attempts(), providers.DEFAULT_MAX_ATTEMPTS)

    def test_retry_delay_honors_retry_after_but_caps_it(self):
        import urllib.error

        from bench.leaderboard import providers

        exc = urllib.error.HTTPError("u", 429, "x", {"Retry-After": "5"}, None)
        self.assertEqual(providers._retry_delay(exc, 1), 5.0)
        huge = urllib.error.HTTPError("u", 429, "x", {"Retry-After": "9999"}, None)
        self.assertEqual(providers._retry_delay(huge, 1), providers.MAX_RETRY_DELAY_S)
        # No header → exponential backoff, also capped.
        self.assertEqual(providers._retry_delay(None, 1), 1.0)
        self.assertEqual(providers._retry_delay(None, 20), providers.MAX_RETRY_DELAY_S)


class MalformedJsonRetryTests(unittest.TestCase):
    def test_malformed_json_retries_then_recovers(self):
        bodies = ["{not json", json.dumps(_fake_openai_body())]
        calls = {"n": 0}

        def fake_urlopen(request, timeout=None):
            body = bodies[calls["n"]]
            calls["n"] += 1
            return _FakeHTTPResponse_raw(body)

        with patch("bench.leaderboard.providers.os.environ", {"OPENROUTER_API_KEY": "k"}), patch(
            "bench.leaderboard.providers.urllib.request.urlopen", side_effect=fake_urlopen
        ), patch("bench.leaderboard.providers.time.sleep"):
            resp = generate_response(
                "openrouter:qwen/q:free", prompt="x", task=SimpleNamespace()
            )
        self.assertEqual(calls["n"], 2)  # retried once, then succeeded
        self.assertEqual(resp.num_model_calls, 2)

    def test_malformed_json_exhausts_then_fails(self):
        from bench.leaderboard.schemas import ProviderFailure

        def fake_urlopen(request, timeout=None):
            return _FakeHTTPResponse_raw("{still not json")

        with patch("bench.leaderboard.providers.os.environ", {"OPENROUTER_API_KEY": "k", "IOTBENCH_PROVIDER_MAX_ATTEMPTS": "2"}), patch(
            "bench.leaderboard.providers.urllib.request.urlopen", side_effect=fake_urlopen
        ), patch("bench.leaderboard.providers.time.sleep"):
            with self.assertRaises(ProviderFailure):
                generate_response("openrouter:qwen/q:free", prompt="x", task=SimpleNamespace())


class TransportErrorRetryTests(unittest.TestCase):
    def test_incomplete_read_is_retried_then_recovers(self):
        import http.client

        class _ReadRaises:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                raise http.client.IncompleteRead(b"1364 bytes")

        states = [_ReadRaises(), _FakeHTTPResponse_raw(json.dumps(_fake_openai_body()))]
        calls = {"n": 0}

        def fake_urlopen(request, timeout=None):
            r = states[calls["n"]]
            calls["n"] += 1
            return r

        with patch("bench.leaderboard.providers.os.environ", {"OPENROUTER_API_KEY": "k"}), patch(
            "bench.leaderboard.providers.urllib.request.urlopen", side_effect=fake_urlopen
        ), patch("bench.leaderboard.providers.time.sleep"):
            resp = generate_response("openrouter:m:free", prompt="x", task=SimpleNamespace())
        self.assertEqual(calls["n"], 2)
        self.assertEqual(resp.num_model_calls, 2)


class _FakeHTTPResponse_raw:
    """Like _FakeHTTPResponse but returns an arbitrary (possibly invalid) body."""

    def __init__(self, body: str):
        self._buf = io.BytesIO(body.encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._buf.read()


class FixtureReferenceProviderTests(unittest.TestCase):
    """The fixture provider must locate the reference source for every build
    kind: Arduino keeps <name>.ino, ESP-IDF nests main/main.c, Zephyr nests
    src/main.c."""

    def _run(self, tmp, build_kind, rel_source):
        import pathlib

        from bench.leaderboard import providers

        sketch_root = pathlib.Path(tmp) / "case" / "sketch" / "demo"
        source = sketch_root / rel_source
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("// reference\n", encoding="utf-8")
        task = SimpleNamespace(
            sketch_name="demo",
            board_profile=SimpleNamespace(build_kind=build_kind),
        )
        with patch.object(providers, "case_dir_for_task", return_value=pathlib.Path(tmp) / "case"):
            resp = generate_response("fixture:reference", prompt="", task=task)
        self.assertEqual(resp.text, "// reference\n")
        self.assertEqual(resp.raw["provider"], "fixture:reference")
        self.assertTrue(resp.raw["source"].endswith(rel_source.replace("/", "\\")) or resp.raw["source"].endswith(rel_source))

    def test_arduino_reference_layout(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, "arduino", "demo.ino")

    def test_espidf_reference_layout(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, "espidf", "main/main.c")

    def test_zephyr_reference_layout(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, "zephyr", "src/main.c")

    def test_unknown_build_kind_rejected(self):
        import pathlib
        import tempfile

        from bench.leaderboard import providers

        with tempfile.TemporaryDirectory() as tmp:
            task = SimpleNamespace(
                sketch_name="demo",
                board_profile=SimpleNamespace(build_kind="riscv_mystery"),
            )
            with patch.object(
                providers, "case_dir_for_task", return_value=pathlib.Path(tmp) / "case"
            ):
                with self.assertRaises(ConfigError):
                    generate_response("fixture:reference", prompt="", task=task)


if __name__ == "__main__":
    unittest.main()

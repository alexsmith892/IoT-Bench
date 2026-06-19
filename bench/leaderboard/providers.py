from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from bench.config import ConfigError, TaskConfig
from bench.runner import case_dir_for_task

from .schemas import ProviderFailure, ProviderResponse


RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
FATAL_HTTP_STATUS = {401, 403}
OPENAI_COMPATIBLE_URL = "/chat/completions"

# Free-tier aggregators (OpenRouter free pool, shared upstream providers) throttle
# aggressively with short Retry-After windows; 3 attempts is too few to ride out a
# transient upstream saturation. Default to a more patient policy, overridable via
# env so a paid run can keep it tight. Per-attempt waits are capped so a pathological
# Retry-After can't stall a sweep indefinitely.
DEFAULT_MAX_ATTEMPTS = 6
MAX_RETRY_DELAY_S = 30.0


def _provider_max_attempts() -> int:
    raw = os.environ.get("IOTBENCH_PROVIDER_MAX_ATTEMPTS")
    if not raw:
        return DEFAULT_MAX_ATTEMPTS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS
    return value if value >= 1 else DEFAULT_MAX_ATTEMPTS

# OpenAI-compatible providers selected by `<prefix>:<model>`. Each shares the
# same wire format; only the default endpoint, default key env var, and whether
# a key is mandatory differ. `local` defaults to Ollama and needs no key.
_OPENAI_COMPAT_PROVIDERS = {
    "openai": {
        "default_base": "https://api.openai.com/v1",
        "default_key_env": "OPENAI_API_KEY",
        "require_key": True,
    },
    "gemini": {
        "default_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_key_env": "GEMINI_API_KEY",
        "require_key": True,
    },
    "openrouter": {
        "default_base": "https://openrouter.ai/api/v1",
        "default_key_env": "OPENROUTER_API_KEY",
        "require_key": True,
    },
    "local": {
        "default_base": "http://localhost:11434/v1",
        "default_key_env": None,
        "require_key": False,
    },
}


def generate_response(
    model: str,
    *,
    prompt: str,
    task: TaskConfig,
    api_base: str | None = None,
    api_key_env: str | None = None,
    temperature: float = 0.2,
    top_p: float = 1.0,
    max_tokens: int = 4096,
    seed: int | None = None,
) -> ProviderResponse:
    if model == "fixture:reference":
        return _fixture_reference(task)
    if model.startswith("file:"):
        return _file_provider(model[5:])
    prefix, sep, model_name = model.partition(":")
    if sep and prefix == "anthropic":
        return _anthropic(
            model_name,
            prompt=prompt,
            api_base=api_base,
            api_key_env=api_key_env or "ANTHROPIC_API_KEY",
            temperature=temperature,
            max_tokens=max_tokens,
        )
    spec = _OPENAI_COMPAT_PROVIDERS.get(prefix) if sep else None
    if spec is not None:
        return _openai_compatible(
            model_name,
            provider=prefix,
            prompt=prompt,
            api_base=api_base,
            api_key_env=api_key_env or spec["default_key_env"],
            default_base=spec["default_base"],
            require_key=spec["require_key"],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            seed=seed,
        )
    raise ConfigError(f"unsupported leaderboard model provider {model!r}")


# OpenAI's gpt-5 and o-series reject `max_tokens` (require `max_completion_tokens`)
# and reject `temperature`/`top_p` != default. This only applies when talking to
# OpenAI directly; aggregators (OpenRouter) and local servers accept the legacy
# params, so the adjustment is scoped to the `openai:` provider.
_OPENAI_NEW_FAMILY_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_new_openai_family(model: str) -> bool:
    name = model.strip().lower()
    return any(name == p or name.startswith(p + "-") or name.startswith(p) for p in _OPENAI_NEW_FAMILY_PREFIXES)


def _build_chat_payload(
    model: str,
    *,
    provider: str,
    prompt: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    seed: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You write embedded firmware. Return only the requested source code."},
            {"role": "user", "content": prompt},
        ],
    }
    new_family = provider == "openai" and _is_new_openai_family(model)
    payload["max_completion_tokens" if new_family else "max_tokens"] = max_tokens
    if not new_family:
        payload["temperature"] = temperature
        payload["top_p"] = top_p
        if seed is not None:
            payload["seed"] = seed
    return payload


def _fixture_reference(task: TaskConfig) -> ProviderResponse:
    start = time.perf_counter()
    source = _reference_source_path(task)
    text = source.read_text(encoding="utf-8")
    return ProviderResponse(
        text=text,
        raw={"provider": "fixture:reference", "source": str(source)},
        usage=None,
        latency_s=round(time.perf_counter() - start, 6),
    )


def _reference_source_path(task: TaskConfig) -> Path:
    """Locate the single reference source the fixture provider returns.

    The reference layout differs per build kind: Arduino keeps a top-level
    ``<name>.ino``, ESP-IDF nests ``main/main.c``, and Zephyr nests
    ``src/main.c``. The leaderboard extractor consumes one source file in all
    three cases, so the fixture provider returns that file verbatim.
    """

    sketch_dir = case_dir_for_task(task) / "sketch" / task.sketch_name
    build_kind = task.board_profile.build_kind
    if build_kind == "arduino":
        primary = sketch_dir / f"{task.sketch_name}.ino"
        glob = "*.ino"
    elif build_kind == "espidf":
        primary = sketch_dir / "main" / "main.c"
        glob = "main/*.c*"
    elif build_kind == "zephyr":
        primary = sketch_dir / "src" / "main.c"
        glob = "src/*.c"
    else:
        raise ConfigError(f"fixture provider does not support build kind {build_kind!r}")
    if primary.exists():
        return primary
    matches = sorted(sketch_dir.glob(glob))
    if len(matches) != 1:
        raise ConfigError(
            f"fixture provider could not locate one reference source ({glob}) under {sketch_dir}"
        )
    return matches[0]


def _file_provider(path_text: str) -> ProviderResponse:
    start = time.perf_counter()
    path = Path(path_text)
    if not path.exists():
        raise ConfigError(f"file provider source not found: {path}")
    return ProviderResponse(
        text=path.read_text(encoding="utf-8"),
        raw={"provider": "file", "source": str(path)},
        usage=None,
        latency_s=round(time.perf_counter() - start, 6),
    )


_ANTHROPIC_SYSTEM = "You write embedded firmware. Return only the requested source code."
_ANTHROPIC_VERSION = "2023-06-01"


def _anthropic(
    model: str,
    *,
    prompt: str,
    api_base: str | None,
    api_key_env: str,
    temperature: float,
    max_tokens: int,
) -> ProviderResponse:
    """Anthropic Messages API adapter (distinct wire format from OpenAI).

    Uses POST /v1/messages with x-api-key + anthropic-version headers, a
    top-level `system`, and a single user message; usage is normalized into the
    same provider-agnostic schema as the OpenAI-compatible path. Model id is
    whatever follows `anthropic:` (e.g. anthropic:claude-opus-4-8).
    """

    key = os.environ.get(api_key_env)
    if not key:
        raise ConfigError(f"environment variable {api_key_env} is required for this provider")
    base = (api_base or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
    url = base + "/v1/messages"
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": _ANTHROPIC_SYSTEM,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "content-type": "application/json",
        "anthropic-version": _ANTHROPIC_VERSION,
        "x-api-key": key,
    }
    sanitized_request = {"url": url, "headers": {"anthropic-version": _ANTHROPIC_VERSION}, "body": payload}
    raw = _post_with_retry(url, headers, payload, sanitized_request)
    text = _anthropic_text(raw)
    if text is None:
        raise ProviderFailure(
            "anthropic provider response did not contain text content",
            {"request": sanitized_request, "response": raw["_response"]},
            raw["_latency_s"],
            raw["_attempt"],
        )
    return ProviderResponse(
        text=text,
        raw={"request": sanitized_request, "response": raw["_response"]},
        usage=_normalize_anthropic_usage(raw["_response"].get("usage")),
        latency_s=raw["_latency_s"],
        num_model_calls=raw["_attempt"],
    )


def _anthropic_text(raw: dict[str, Any]) -> str | None:
    blocks = raw["_response"].get("content")
    if not isinstance(blocks, list):
        return None
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    return text if text.strip() else None


def _normalize_anthropic_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    cached = value.get("cache_read_input_tokens")
    if input_tokens is None and output_tokens is None and cached is None:
        return None
    total = None
    if input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "prompt_tokens": input_tokens,
        "output_tokens": output_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total,
        "reasoning_tokens": None,
        "cached_input_tokens": cached,
        "cost": None,
        "usage_source": "provider",
    }


def _post_with_retry(
    url: str, headers: dict[str, str], payload: dict[str, Any], sanitized_request: dict[str, Any]
) -> dict[str, Any]:
    """POST JSON with the same retry/backoff policy as the OpenAI path.

    Returns the parsed response under `_response` plus `_latency_s`/`_attempt`
    bookkeeping; raises ConfigError on fatal HTTP and ProviderFailure otherwise.
    """

    start = time.perf_counter()
    last_raw: dict[str, Any] | None = None
    max_attempts = _provider_max_attempts()
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=dict(headers)
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8")
            try:
                raw = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ProviderFailure(
                    "provider returned malformed JSON",
                    {"request": sanitized_request, "response": {"body": body}},
                    round(time.perf_counter() - start, 6),
                    attempt,
                ) from exc
            return {"_response": raw, "_latency_s": round(time.perf_counter() - start, 6), "_attempt": attempt}
        except ProviderFailure:
            raise
        except urllib.error.HTTPError as exc:
            body = _read_http_error_body(exc)
            last_raw = {"request": sanitized_request, "response": {"status": exc.code, "reason": exc.reason, "body": body}}
            if exc.code in FATAL_HTTP_STATUS or exc.code not in RETRYABLE_HTTP_STATUS:
                raise ConfigError(f"provider HTTP {exc.code}: {exc.reason}") from exc
            if attempt < max_attempts:
                time.sleep(_retry_delay(exc, attempt))
                continue
            raise ProviderFailure(
                f"provider failed after {attempt} attempt(s): HTTP {exc.code}",
                last_raw,
                round(time.perf_counter() - start, 6),
                attempt,
            ) from exc
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError) as exc:
            last_raw = {"request": sanitized_request, "response": {"error": type(exc).__name__, "reason": str(exc)}}
            if attempt < max_attempts:
                time.sleep(_retry_delay(None, attempt))
                continue
            raise ProviderFailure(
                f"provider failed after {attempt} attempt(s): {exc}",
                last_raw,
                round(time.perf_counter() - start, 6),
                attempt,
            ) from exc
    raise ProviderFailure(
        "provider failed without a response",
        last_raw or {"request": sanitized_request, "response": None},
        round(time.perf_counter() - start, 6),
        max_attempts,
    )


def _openai_compatible(
    model: str,
    *,
    provider: str = "openai",
    prompt: str,
    api_base: str | None,
    api_key_env: str | None,
    default_base: str,
    require_key: bool,
    temperature: float,
    top_p: float,
    max_tokens: int,
    seed: int | None,
) -> ProviderResponse:
    key = os.environ.get(api_key_env) if api_key_env else None
    if require_key and not key:
        raise ConfigError(
            f"environment variable {api_key_env} is required for this provider"
        )
    base = (api_base or os.environ.get("OPENAI_BASE_URL") or default_base).rstrip("/")
    url = base + OPENAI_COMPATIBLE_URL
    payload = _build_chat_payload(
        model,
        provider=provider,
        prompt=prompt,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
    )
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    sanitized_request = {
        "url": url,
        "headers": {"Content-Type": "application/json"},
        "body": payload,
    }
    start = time.perf_counter()
    last_raw: dict[str, Any] | None = None
    max_attempts = _provider_max_attempts()
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=dict(headers),
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response_body = response.read().decode("utf-8")
            try:
                raw = json.loads(response_body)
            except json.JSONDecodeError as exc:
                # A 200 with a corrupt/truncated body is a transient glitch on
                # flaky (free-tier) endpoints; retry rather than burning the
                # attempt as a one-shot failure.
                last_raw = {
                    "request": sanitized_request,
                    "response": {"body": response_body},
                }
                if attempt < max_attempts:
                    time.sleep(_retry_delay(None, attempt))
                    continue
                raise ProviderFailure(
                    "openai-compatible provider returned malformed JSON",
                    last_raw,
                    round(time.perf_counter() - start, 6),
                    attempt,
                ) from exc
            raw_with_request = {
                "request": sanitized_request,
                "response": raw,
            }
            text = _message_content(raw)
            if text is None:
                raise ProviderFailure(
                    "openai-compatible provider response did not contain message content",
                    raw_with_request,
                    round(time.perf_counter() - start, 6),
                    attempt,
                )
            usage = _normalize_usage(raw.get("usage"))
            raw_with_request = {
                "request": sanitized_request,
                "response": raw,
            }
            return ProviderResponse(
                text=text,
                raw=raw_with_request,
                usage=usage,
                latency_s=round(time.perf_counter() - start, 6),
                num_model_calls=attempt,
            )
        except ProviderFailure:
            raise
        except urllib.error.HTTPError as exc:
            body = _read_http_error_body(exc)
            last_raw = {
                "request": sanitized_request,
                "response": {
                    "status": exc.code,
                    "reason": exc.reason,
                    "body": body,
                },
            }
            if exc.code in FATAL_HTTP_STATUS or exc.code not in RETRYABLE_HTTP_STATUS:
                raise ConfigError(f"openai-compatible provider HTTP {exc.code}: {exc.reason}") from exc
            if attempt < max_attempts:
                time.sleep(_retry_delay(exc, attempt))
                continue
            raise ProviderFailure(
                f"openai-compatible provider failed after {attempt} attempt(s): HTTP {exc.code}",
                last_raw,
                round(time.perf_counter() - start, 6),
                attempt,
            ) from exc
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError) as exc:
            last_raw = {
                "request": sanitized_request,
                "response": {
                    "error": type(exc).__name__,
                    "reason": str(exc),
                },
            }
            if attempt < max_attempts:
                time.sleep(_retry_delay(None, attempt))
                continue
            raise ProviderFailure(
                f"openai-compatible provider failed after {attempt} attempt(s): {exc}",
                last_raw,
                round(time.perf_counter() - start, 6),
                attempt,
            ) from exc
    raise ProviderFailure(
        "openai-compatible provider failed without a response",
        last_raw or {"request": sanitized_request, "response": None},
        round(time.perf_counter() - start, 6),
        max_attempts,
    )


def _message_content(raw: dict[str, Any]) -> str | None:
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    return content if isinstance(content, str) and content.strip() else None


def _normalize_usage(value: Any) -> dict[str, Any] | None:
    """Map provider usage metadata into one provider-agnostic schema.

    Authoritative token counts come from the API response (OpenRouter, OpenAI,
    Gemini, Groq, local servers all populate `prompt_tokens`/`completion_tokens`
    or the `*_tokens` aliases). Optional fields — reasoning tokens, cached input
    tokens, and provider-reported cost — are filled when present, else null. New
    providers map into the same keys.
    """

    if not isinstance(value, dict):
        return None
    prompt_tokens = value.get("prompt_tokens", value.get("input_tokens"))
    completion_tokens = value.get("completion_tokens", value.get("output_tokens"))
    total_tokens = value.get("total_tokens")
    prompt_details = value.get("prompt_tokens_details")
    completion_details = value.get("completion_tokens_details")
    cached = value.get("cached_tokens", value.get("cached_input_tokens"))
    if cached is None and isinstance(prompt_details, dict):
        cached = prompt_details.get("cached_tokens")
    reasoning = value.get("reasoning_tokens")
    if reasoning is None and isinstance(completion_details, dict):
        reasoning = completion_details.get("reasoning_tokens")
    cost = value.get("cost")
    if all(v is None for v in (prompt_tokens, completion_tokens, total_tokens, cached, reasoning, cost)):
        return None
    return {
        "input_tokens": prompt_tokens,
        "prompt_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": reasoning,
        "cached_input_tokens": cached,
        "cost": cost,
        "usage_source": "provider",
    }


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read()
    except Exception:
        return ""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body)


def _retry_delay(exc: urllib.error.HTTPError | None, attempt: int) -> float:
    if exc is not None:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after:
            try:
                return min(MAX_RETRY_DELAY_S, max(0.0, float(retry_after)))
            except ValueError:
                pass
    return min(MAX_RETRY_DELAY_S, float(2 ** (attempt - 1)))

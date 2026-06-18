from __future__ import annotations

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


def generate_response(
    model: str,
    *,
    prompt: str,
    task: TaskConfig,
    api_base: str | None = None,
    api_key_env: str = "OPENAI_API_KEY",
    temperature: float = 0.2,
    top_p: float = 1.0,
    max_tokens: int = 4096,
    seed: int | None = None,
) -> ProviderResponse:
    if model == "fixture:reference":
        return _fixture_reference(task)
    if model.startswith("file:"):
        return _file_provider(model[5:])
    if model.startswith("openai:"):
        return _openai_compatible(
            model[7:],
            prompt=prompt,
            api_base=api_base,
            api_key_env=api_key_env,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            seed=seed,
        )
    raise ConfigError(f"unsupported leaderboard model provider {model!r}")


def _fixture_reference(task: TaskConfig) -> ProviderResponse:
    start = time.perf_counter()
    sketch_dir = case_dir_for_task(task) / "sketch" / task.sketch_name
    source = sketch_dir / f"{task.sketch_name}.ino"
    if not source.exists():
        matches = sorted(sketch_dir.glob("*.ino"))
        if len(matches) != 1:
            raise ConfigError(f"fixture provider could not locate one reference .ino under {sketch_dir}")
        source = matches[0]
    text = source.read_text(encoding="utf-8")
    return ProviderResponse(
        text=text,
        raw={"provider": "fixture:reference", "source": str(source)},
        usage=None,
        latency_s=round(time.perf_counter() - start, 6),
    )


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


def _openai_compatible(
    model: str,
    *,
    prompt: str,
    api_base: str | None,
    api_key_env: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    seed: int | None,
) -> ProviderResponse:
    key = os.environ.get(api_key_env)
    if not key:
        raise ConfigError(f"environment variable {api_key_env} is required for openai provider")
    base = (api_base or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    url = base + OPENAI_COMPATIBLE_URL
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You write embedded firmware. Return only the requested source code."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    if seed is not None:
        payload["seed"] = seed
    sanitized_request = {
        "url": url,
        "headers": {"Content-Type": "application/json"},
        "body": payload,
    }
    start = time.perf_counter()
    last_raw: dict[str, Any] | None = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response_body = response.read().decode("utf-8")
            try:
                raw = json.loads(response_body)
            except json.JSONDecodeError as exc:
                raise ProviderFailure(
                    "openai-compatible provider returned malformed JSON",
                    {
                        "request": sanitized_request,
                        "response": {"body": response_body},
                    },
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
        except (urllib.error.URLError, TimeoutError) as exc:
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
    if not isinstance(value, dict):
        return None
    prompt_tokens = value.get("prompt_tokens", value.get("input_tokens"))
    completion_tokens = value.get("completion_tokens", value.get("output_tokens"))
    total_tokens = value.get("total_tokens")
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None
    return {
        "input_tokens": prompt_tokens,
        "prompt_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
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
                return max(0.0, float(retry_after))
            except ValueError:
                pass
    return float(2 ** (attempt - 1))

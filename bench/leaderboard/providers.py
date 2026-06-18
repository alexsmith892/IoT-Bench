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

from .schemas import ProviderResponse


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
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base + "/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    start = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = json.loads(response.read().decode("utf-8"))
            text = raw["choices"][0]["message"]["content"]
            raw_with_request = {
                "request": {key: value for key, value in payload.items() if key != "messages"},
                "response": raw,
            }
            return ProviderResponse(
                text=text,
                raw=raw_with_request,
                usage=raw.get("usage"),
                latency_s=round(time.perf_counter() - start, 6),
            )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise ConfigError(f"openai-compatible provider failed: {last_error}")


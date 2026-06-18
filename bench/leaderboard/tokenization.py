"""Optional prompt tokenization for the base/skill input-token split.

A real tokenizer (tiktoken) is used when it is installed *and* its encoding is
locally available. We never estimate token counts: if no tokenizer is present,
the split is reported as ``None`` and reports fall back to the exactly-measured
character proxies (`base_prompt_chars` / `skill_prompt_chars`). Install tiktoken
to activate token counts — `pip install tiktoken` (first use caches the vocab).
"""

from __future__ import annotations

from typing import Any

# A single consistent encoder is used for every model so the base-vs-skill split
# ratio is comparable across providers. The name is recorded per attempt.
_ENCODING_NAME = "o200k_base"
_TOKENIZER_LABEL = f"tiktoken/{_ENCODING_NAME}"

_encoder: Any = None
_encoder_loaded = False


def _get_encoder() -> Any:
    global _encoder, _encoder_loaded
    if _encoder_loaded:
        return _encoder
    _encoder_loaded = True
    try:
        import tiktoken

        _encoder = tiktoken.get_encoding(_ENCODING_NAME)
    except Exception:
        # Not installed, or the encoding is not cached and cannot be fetched
        # offline. Stay silent and let callers fall back to char proxies.
        _encoder = None
    return _encoder


def split_token_counts(
    base_text: str, skill_text: str, *, encoder: Any = None
) -> tuple[int | None, int | None, str | None]:
    """Return (base_tokens, skill_tokens, tokenizer_label).

    Token counts are the measured length of each text segment under the encoder.
    When no encoder is available, returns (None, None, None) — never an estimate.
    `encoder` may be injected for testing; it must expose `.encode(str) -> list`.
    """

    enc = encoder if encoder is not None else _get_encoder()
    if enc is None:
        return None, None, None
    label = getattr(enc, "name", None) or _TOKENIZER_LABEL
    return len(enc.encode(base_text)), len(enc.encode(skill_text)), label

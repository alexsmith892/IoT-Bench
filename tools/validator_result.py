#!/usr/bin/env python3
"""Shared result labels and JSON emission for validators."""

from __future__ import annotations

import json
from typing import Any


COMPILE_FAIL = "COMPILE_FAIL"
SIM_INFRA_FAIL = "SIM_INFRA_FAIL"
SIM_OUTPUT_FAIL = "SIM_OUTPUT_FAIL"
FAIL = "FAIL"
PASS = "PASS"

STAGE_COMPILE = "compile"
STAGE_SIM_INFRA = "simulate"
STAGE_SIM_OUTPUT = "vcd_output"
STAGE_BEHAVIOR = "behavior"

LEGACY_CLASSIFICATION = {
    COMPILE_FAIL: "CF",
    SIM_INFRA_FAIL: "CF",
    SIM_OUTPUT_FAIL: "CF",
    FAIL: "BF",
    PASS: "BC",
}

DEFAULT_FAILURE_STAGE = {
    COMPILE_FAIL: STAGE_COMPILE,
    SIM_INFRA_FAIL: STAGE_SIM_INFRA,
    SIM_OUTPUT_FAIL: STAGE_SIM_OUTPUT,
    FAIL: STAGE_BEHAVIOR,
    PASS: None,
}


def emit_result(
    classification: str,
    reason: str,
    metrics: dict[str, Any],
    *,
    failure_stage: str | None = None,
) -> int:
    """Print the stable validator JSON payload."""

    payload = {
        "classification": classification,
        "legacy_classification": LEGACY_CLASSIFICATION[classification],
        "failure_stage": (
            failure_stage
            if failure_stage is not None
            else DEFAULT_FAILURE_STAGE[classification]
        ),
        "reason": reason,
        "metrics": metrics,
    }
    print(json.dumps(payload, indent=2))
    return 0

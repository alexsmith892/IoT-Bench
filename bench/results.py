"""Shared result labels and JSON payload helpers for benchmark validators."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


COMPILE_FAIL = "COMPILE_FAIL"
SIM_INFRA_FAIL = "SIM_INFRA_FAIL"
SIM_OUTPUT_FAIL = "SIM_OUTPUT_FAIL"
FAIL = "FAIL"
PASS = "PASS"

RESULT_CF = "CF"
RESULT_BF = "BF"
RESULT_BC = "BC"

STAGE_COMPILE = "compile"
STAGE_SIM_INFRA = "simulate"
STAGE_SIM_OUTPUT = "sim_output"
STAGE_BEHAVIOR = "behavior"

RESULT_BY_CLASSIFICATION = {
    COMPILE_FAIL: RESULT_CF,
    SIM_INFRA_FAIL: RESULT_CF,
    SIM_OUTPUT_FAIL: RESULT_CF,
    FAIL: RESULT_BF,
    PASS: RESULT_BC,
}

DEFAULT_FAILURE_STAGE = {
    COMPILE_FAIL: STAGE_COMPILE,
    SIM_INFRA_FAIL: STAGE_SIM_INFRA,
    SIM_OUTPUT_FAIL: STAGE_SIM_OUTPUT,
    FAIL: STAGE_BEHAVIOR,
    PASS: None,
}


@dataclass(frozen=True)
class ValidationResult:
    classification: str
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)
    failure_stage: str | None = None

    def payload(self) -> dict[str, Any]:
        return result_payload(
            self.classification,
            self.reason,
            self.metrics,
            failure_stage=self.failure_stage,
        )


def result_payload(
    classification: str,
    reason: str,
    metrics: dict[str, Any] | None = None,
    *,
    failure_stage: str | None = None,
) -> dict[str, Any]:
    """Build the stable JSON result payload used by the benchmark CLI."""

    return {
        "result": RESULT_BY_CLASSIFICATION[classification],
        "classification": classification,
        "failure_stage": (
            failure_stage
            if failure_stage is not None
            else DEFAULT_FAILURE_STAGE[classification]
        ),
        "reason": reason,
        "metrics": metrics or {},
    }


def emit_result(
    classification: str,
    reason: str,
    metrics: dict[str, Any] | None = None,
    *,
    failure_stage: str | None = None,
) -> int:
    print(
        json.dumps(
            result_payload(
                classification,
                reason,
                metrics,
                failure_stage=failure_stage,
            ),
            indent=2,
        )
    )
    return 0

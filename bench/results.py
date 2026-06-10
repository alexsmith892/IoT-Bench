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
RESULT_IF = "IF"
RESULT_BF = "BF"
RESULT_BC = "BC"

STAGE_COMPILE = "compile"
STAGE_SIM_INFRA = "simulate"
STAGE_SIM_OUTPUT = "sim_output"
STAGE_BEHAVIOR = "behavior"

SOURCE_USER_CODE = "user_code"
SOURCE_HARNESS = "harness"
SOURCE_SIMULATOR = "simulator"
SOURCE_ENVIRONMENT = "environment"
SOURCE_ARTIFACT = "artifact"

# Top-level benchmark outcome per internal classification.
#
# CF is reserved for failures attributable to the submission's own source
# (it failed to compile). SIM_INFRA_FAIL and SIM_OUTPUT_FAIL are mapped to IF
# ("inconclusive / infrastructure"): the harness could not obtain a trustworthy
# behavior judgment for reasons not clearly the submission's fault (simulator,
# environment, harness, or a missing/empty/malformed artifact). IF results are
# meant to be retried or excluded from scoring, never charged against the model.
# The detailed `classification`/`failure_stage`/`failure_source` fields still
# carry the precise cause for any consumer that needs to disambiguate further.
RESULT_BY_CLASSIFICATION = {
    COMPILE_FAIL: RESULT_CF,
    SIM_INFRA_FAIL: RESULT_IF,
    SIM_OUTPUT_FAIL: RESULT_IF,
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

DEFAULT_FAILURE_SOURCE = {
    COMPILE_FAIL: SOURCE_USER_CODE,
    SIM_INFRA_FAIL: SOURCE_SIMULATOR,
    SIM_OUTPUT_FAIL: SOURCE_ARTIFACT,
    FAIL: SOURCE_USER_CODE,
    PASS: None,
}


@dataclass(frozen=True)
class ValidationResult:
    classification: str
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)
    failure_stage: str | None = None
    failure_source: str | None = None

    def payload(self) -> dict[str, Any]:
        return result_payload(
            self.classification,
            self.reason,
            self.metrics,
            failure_stage=self.failure_stage,
            failure_source=self.failure_source,
        )


def result_payload(
    classification: str,
    reason: str,
    metrics: dict[str, Any] | None = None,
    *,
    failure_stage: str | None = None,
    failure_source: str | None = None,
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
        "failure_source": (
            failure_source
            if failure_source is not None
            else DEFAULT_FAILURE_SOURCE[classification]
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
    failure_source: str | None = None,
) -> int:
    print(
        json.dumps(
            result_payload(
                classification,
                reason,
                metrics,
                failure_stage=failure_stage,
                failure_source=failure_source,
            ),
            indent=2,
        )
    )
    return 0

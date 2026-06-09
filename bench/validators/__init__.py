"""Reusable validator families for Arduino Mega level-1 tasks."""

from __future__ import annotations

from typing import Any

from bench.config import TaskConfig
from bench.results import FAIL, PASS, ValidationResult
from bench.runner import CasePaths
from bench.serial import (
    SerialLogError,
    contains_text,
    count_occurrences,
    extract_floats,
    extract_ints,
    monotonic_counter_reaches,
    read_serial_log,
)
from bench.static import StaticCheckError, validate_forbidden_calls
from bench.vcd import (
    VcdEvent,
    VcdParseError,
    average,
    build_segments,
    in_range,
    parse_vcd_signal,
    parse_vcd_signals,
    value_ratio,
)


def validate_task(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    family = task.validator_family
    validators = {
        "waveform_frequency": validate_waveform_frequency,
        "morse_sos": validate_morse_sos,
        "no_delay_static_plus_waveform": validate_no_delay_static_plus_waveform,
        "multi_channel_frequency": validate_multi_channel_frequency,
        "pwm_breathing": validate_pwm_breathing,
        "stimulus_to_output": validate_stimulus_to_output,
        "serial_contains_on_stimulus": validate_serial_contains_on_stimulus,
        "serial_count_sequence": validate_serial_count_sequence,
        "debounce_serial": validate_debounce_serial,
        "analog_temperature_serial": validate_analog_temperature_serial,
    }
    if family not in validators:
        return ValidationResult(FAIL, f"unknown validator family: {family}", base_metrics(task, paths))
    result = validators[family](task, paths)
    merged = base_metrics(task, paths)
    merged.update(result.metrics)
    return ValidationResult(
        result.classification,
        result.reason,
        merged,
        failure_stage=result.failure_stage,
    )


def base_metrics(task: TaskConfig, paths: CasePaths) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "task_id": task.task_id,
        "family": task.validator_family,
        "case_path": str(paths.case_dir),
        "sketch_path": str(paths.sketch),
        "diagram_path": str(paths.diagram),
    }
    if paths.scenario:
        metrics["scenario_path"] = str(paths.scenario)
    if paths.vcd:
        metrics["vcd_path"] = str(paths.vcd)
    if paths.serial_log:
        metrics["serial_log_path"] = str(paths.serial_log)
    return metrics


def validate_waveform_frequency(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    params = task.validator_params()
    channel_params = params.get("channels") or {
        task.fixture.get("analyzer", {}).get("channels", [{"signal": "D0"}])[0]["signal"]: params
    }
    return validate_frequency_channels(paths, channel_params)


def validate_multi_channel_frequency(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    return validate_frequency_channels(paths, task.validator_params().get("channels") or {})


def validate_frequency_channels(
    paths: CasePaths, channel_params: dict[str, dict[str, Any]]
) -> ValidationResult:
    if paths.vcd is None:
        return ValidationResult(FAIL, "case does not define a VCD artifact")
    signals = list(channel_params)
    signal_events = parse_vcd_signals(paths.vcd, signals)
    channel_metrics: dict[str, Any] = {}
    for signal, params in channel_params.items():
        result = validate_frequency_events(signal_events[signal], params, signal)
        channel_metrics[signal] = result.metrics
        if result.classification != PASS:
            return ValidationResult(result.classification, result.reason, {"channels": channel_metrics})
    return ValidationResult(PASS, "all waveform frequencies matched expectations", {"channels": channel_metrics})


def validate_frequency_events(
    events: list[VcdEvent], params: dict[str, Any], signal: str
) -> ValidationResult:
    metrics: dict[str, Any] = {"num_transitions": max(0, len(events) - 1)}
    min_cycles = int(params.get("min_valid_cycles_after_startup", 4))
    half_range = params.get("half_period_range_s", [0.45, 0.55])
    period_range = params.get("full_period_range_s", [0.9, 1.1])
    duty_range = params.get("duty_cycle_range", [0.4, 0.6])

    if len(events) < 2:
        return ValidationResult(FAIL, f"{signal} has too few events", metrics)
    segments = build_segments(events)
    if len(segments) < (min_cycles * 2 + 1):
        return ValidationResult(
            FAIL,
            f"too few {signal} transitions for {min_cycles} post-startup cycles",
            metrics,
        )

    steady_segments = segments[1:]
    cycles: list[tuple[float, float]] = []
    index = 0
    while index + 1 < len(steady_segments) and len(cycles) < min_cycles:
        first = steady_segments[index]
        second = steady_segments[index + 1]
        if first.value == second.value:
            return ValidationResult(
                FAIL,
                f"{signal} does not alternate cleanly between LOW and HIGH",
                metrics,
            )
        high = first.duration_s if first.value == 1 else second.duration_s
        low = first.duration_s if first.value == 0 else second.duration_s
        cycles.append((high, low))
        index += 2

    if len(cycles) < min_cycles:
        return ValidationResult(
            FAIL,
            f"only {len(cycles)} complete post-startup cycles were captured on {signal}",
            metrics,
        )

    high_durations = [high for high, _low in cycles]
    low_durations = [low for _high, low in cycles]
    periods = [high + low for high, low in cycles]
    duty_cycles = [high / (high + low) for high, low in cycles]
    avg_period = average(periods)
    metrics.update(
        {
            "high_durations_s": rounded(high_durations),
            "low_durations_s": rounded(low_durations),
            "periods_s": rounded(periods),
            "average_period_s": rounded_scalar(avg_period),
            "average_frequency_hz": rounded_scalar(1.0 / avg_period) if avg_period else None,
            "average_duty_cycle": rounded_scalar(average(duty_cycles)),
        }
    )

    for duration in high_durations:
        if not in_range(duration, half_range):
            return ValidationResult(
                FAIL,
                f"{signal} HIGH duration {duration:.6f}s is outside tolerance",
                metrics,
            )
    for duration in low_durations:
        if not in_range(duration, half_range):
            return ValidationResult(
                FAIL,
                f"{signal} LOW duration {duration:.6f}s is outside tolerance",
                metrics,
            )
    for period in periods:
        if not in_range(period, period_range):
            return ValidationResult(
                FAIL,
                f"{signal} period {period:.6f}s is outside tolerance",
                metrics,
            )
    for duty_cycle in duty_cycles:
        if not in_range(duty_cycle, duty_range):
            return ValidationResult(
                FAIL,
                f"{signal} duty cycle {duty_cycle:.3f} is outside tolerance",
                metrics,
            )

    return ValidationResult(PASS, f"{signal} waveform frequency is within tolerance", metrics)


def validate_no_delay_static_plus_waveform(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    metrics = {"static_check_passed": False}
    forbidden = task.static_checks.get("forbidden_calls") or task.validator_params().get(
        "forbidden_calls", ["delay", "delayMicroseconds"]
    )
    try:
        validate_forbidden_calls(paths.sketch, list(forbidden))
    except StaticCheckError as exc:
        return ValidationResult(FAIL, str(exc), metrics)
    metrics["static_check_passed"] = True
    result = validate_waveform_frequency(task, paths)
    result.metrics.update(metrics)
    return result


def validate_morse_sos(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    if paths.vcd is None:
        return ValidationResult(FAIL, "case does not define a VCD artifact")
    params = task.validator_params()
    signal = params.get("channel", "D0")
    events = parse_vcd_signal(paths.vcd, signal)
    metrics: dict[str, Any] = {"num_transitions": max(0, len(events) - 1)}
    if len(events) < 18:
        return ValidationResult(FAIL, f"too few {signal} transitions to contain SOS", metrics)
    segments = build_segments(events)
    unit_s = float(params.get("unit_s", 0.2))
    tolerance = float(params.get("timing_tolerance", 0.05))
    expected_units = params.get("high_units", [1, 1, 1, 3, 3, 3, 1, 1, 1])
    expected_gap_units = params.get("gap_units", [1, 1, 3, 1, 1, 3, 1, 1])

    for start in range(0, len(segments) - 16):
        candidate = segments[start : start + 17]
        if candidate[0].value != 1:
            continue
        if any(segment.value != (1 if index % 2 == 0 else 0) for index, segment in enumerate(candidate)):
            continue
        highs = [candidate[index].duration_s for index in range(0, 17, 2)]
        gaps = [candidate[index].duration_s for index in range(1, 16, 2)]
        if matches_units(highs, expected_units, unit_s, tolerance) and matches_units(
            gaps, expected_gap_units, unit_s, tolerance
        ):
            metrics.update(
                {
                    "match_start_s": rounded_scalar(candidate[0].start_s),
                    "unit_estimate_s": rounded_scalar(
                        estimate_unit(highs, gaps, expected_units, expected_gap_units)
                    ),
                    "high_durations_s": rounded(highs),
                    "gap_durations_s": rounded(gaps),
                }
            )
            return ValidationResult(PASS, f"found valid SOS Morse sequence on {signal}", metrics)

    return ValidationResult(FAIL, f"no valid SOS Morse sequence found on {signal}", metrics)


def matches_units(
    durations: list[float], expected_units: list[int], unit_s: float, tolerance: float
) -> bool:
    return all(
        abs(duration - expected * unit_s) <= expected * unit_s * tolerance
        for duration, expected in zip(durations, expected_units)
    )


def estimate_unit(
    highs: list[float],
    gaps: list[float],
    expected_units: list[int],
    expected_gap_units: list[int],
) -> float:
    samples = [
        duration / units for duration, units in zip(highs, expected_units)
    ] + [
        duration / units for duration, units in zip(gaps, expected_gap_units)
    ]
    return sum(samples) / len(samples)


def validate_pwm_breathing(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    if paths.vcd is None:
        return ValidationResult(FAIL, "case does not define a VCD artifact")
    params = task.validator_params()
    signal = params.get("channel", "D0")
    events = parse_vcd_signal(paths.vcd, signal)
    metrics: dict[str, Any] = {"num_transitions": max(0, len(events) - 1)}
    levels = int(params.get("levels", 50))
    step_interval_s = float(params.get("step_interval_s", 0.010))
    full_range = params.get("full_period_range_s", [0.95, 1.05])
    duty_tolerance = float(params.get("duty_tolerance", 0.03))

    if len(events) < 100:
        return ValidationResult(FAIL, f"too few {signal} transitions for PWM breathing analysis", metrics)
    segments = build_segments(events)
    total_duration = events[-1].timestamp_s - events[0].timestamp_s
    if total_duration < full_range[0]:
        return ValidationResult(FAIL, "trace is too short to contain one breathing period", metrics)

    expected = expected_breathing_sequence(levels)
    last_start = events[-1].timestamp_s - step_interval_s * len(expected)
    if last_start <= events[0].timestamp_s:
        return ValidationResult(FAIL, f"trace is too short to measure {len(expected)} breathing steps", metrics)

    best_metrics: dict[str, Any] | None = None
    best_score = float("inf")
    start = events[0].timestamp_s
    while start <= min(events[0].timestamp_s + 0.100, last_start):
        measured = [
            value_ratio(
                segments,
                start + index * step_interval_s,
                start + (index + 1) * step_interval_s,
            )
            for index in range(len(expected))
        ]
        score = sum(abs(actual - wanted) for actual, wanted in zip(measured, expected))
        if score < best_score:
            best_score = score
            best_metrics = {
                "match_start_s": rounded_scalar(start),
                "measured_duty_cycles": rounded(measured, digits=5),
                "expected_duty_cycles": rounded(expected, digits=5),
                "step_intervals_s": rounded([step_interval_s for _ in range(len(expected) - 1)]),
                "average_pwm_period_s": rounded_scalar(average_pwm_period(events)),
                "breathing_period_s": rounded_scalar(step_interval_s * len(expected)),
                "monotonicity_passed": is_monotonic_breath(measured, levels, duty_tolerance),
            }
        start += 0.001

    if best_metrics is None:
        return ValidationResult(FAIL, "could not align breathing windows", metrics)
    metrics.update(best_metrics)
    if not in_range(float(metrics["breathing_period_s"]), full_range):
        return ValidationResult(FAIL, "breathing period is outside tolerance", metrics)
    if not metrics["monotonicity_passed"]:
        return ValidationResult(FAIL, "duty cycle sequence is not monotonic rise then fall", metrics)
    for actual, wanted in zip(metrics["measured_duty_cycles"], metrics["expected_duty_cycles"]):
        if abs(actual - wanted) > duty_tolerance:
            return ValidationResult(
                FAIL,
                f"duty cycle {actual:.3f} is outside tolerance for expected {wanted:.3f}",
                metrics,
            )
    return ValidationResult(PASS, f"{signal} shows PWM breathing behavior within tolerance", metrics)


def expected_breathing_sequence(levels: int) -> list[float]:
    rising = [(index + 1) / levels for index in range(levels)]
    return rising + list(reversed(rising))


def is_monotonic_breath(values: list[float], levels: int, tolerance: float) -> bool:
    if len(values) < levels * 2:
        return False
    rising = values[:levels]
    falling = values[levels : levels * 2]
    return all(a <= b + tolerance for a, b in zip(rising, rising[1:])) and all(
        a + tolerance >= b for a, b in zip(falling, falling[1:])
    )


def average_pwm_period(events: list[VcdEvent]) -> float | None:
    rising_edges = [
        current.timestamp_s
        for previous, current in zip(events, events[1:])
        if previous.value == 0 and current.value == 1
    ]
    periods = [
        following - current
        for current, following in zip(rising_edges, rising_edges[1:])
        if following - current < 0.005
    ]
    return average(periods)


def validate_stimulus_to_output(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    if paths.vcd is None:
        return ValidationResult(FAIL, "case does not define a VCD artifact")
    params = task.validator_params()
    signal = params.get("channel", "D0")
    events = parse_vcd_signal(paths.vcd, signal)
    segments = build_segments(events)
    active_min = float(params.get("active_ratio_min", 0.8))
    inactive_max = float(params.get("inactive_ratio_max", 0.2))
    active_ratios = [
        value_ratio(segments, window[0], window[1])
        for window in params.get("active_windows_s", [])
    ]
    inactive_ratios = [
        value_ratio(segments, window[0], window[1])
        for window in params.get("inactive_windows_s", [])
    ]
    metrics = {
        "active_high_ratios": rounded(active_ratios, digits=4),
        "inactive_high_ratios": rounded(inactive_ratios, digits=4),
    }
    if any(ratio < active_min for ratio in active_ratios):
        return ValidationResult(FAIL, f"{signal} was not active during button press window", metrics)
    if any(ratio > inactive_max for ratio in inactive_ratios):
        return ValidationResult(FAIL, f"{signal} stayed active outside press window", metrics)
    return ValidationResult(PASS, f"{signal} follows configured stimulus windows", metrics)


def validate_serial_contains_on_stimulus(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    text = read_serial_log_or_fail(paths)
    params = task.validator_params()
    expected = params.get("expected_texts") or [params.get("expected_text")]
    min_count = int(params.get("min_count", 1))
    metrics = {"expected_texts": expected, "counts": {}}
    for item in expected:
        count = count_occurrences(text, item, case_sensitive=params.get("case_sensitive", True))
        metrics["counts"][item] = count
        if count < min_count:
            return ValidationResult(FAIL, f"serial log is missing expected text: {item}", metrics)
    return ValidationResult(PASS, "serial log contains expected stimulus response text", metrics)


def validate_serial_count_sequence(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    text = read_serial_log_or_fail(paths)
    params = task.validator_params()
    expected_count = int(params.get("expected_count", 3))
    values = extract_ints(text)
    metrics = {"integers": values, "expected_count": expected_count}
    if not monotonic_counter_reaches(values, expected_count):
        return ValidationResult(
            FAIL,
            f"serial log does not show a monotonic count reaching {expected_count}",
            metrics,
        )
    return ValidationResult(PASS, "serial log shows a monotonic count sequence", metrics)


def validate_debounce_serial(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    text = read_serial_log_or_fail(paths)
    params = task.validator_params()
    expected_text = params.get("expected_text", "Button Pressed!")
    expected_triggers = int(params.get("expected_triggers", 2))
    count = count_occurrences(text, expected_text)
    metrics = {
        "expected_text": expected_text,
        "observed_trigger_count": count,
        "expected_triggers": expected_triggers,
    }
    if count != expected_triggers:
        return ValidationResult(
            FAIL,
            f"expected {expected_triggers} debounced trigger(s), found {count}",
            metrics,
        )
    return ValidationResult(PASS, "serial log shows debounced button trigger count", metrics)


def validate_analog_temperature_serial(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    text = read_serial_log_or_fail(paths)
    params = task.validator_params()
    expected = [float(value) for value in params.get("expected_celsius", [])]
    tolerance = float(params.get("tolerance_celsius", 5.0))
    values = extract_floats(text)
    metrics = {
        "expected_celsius": expected,
        "observed_numbers": rounded(values, digits=3),
        "tolerance_celsius": tolerance,
    }
    for wanted in expected:
        if not any(abs(actual - wanted) <= tolerance for actual in values):
            return ValidationResult(
                FAIL,
                f"serial log does not contain plausible temperature near {wanted:g}C",
                metrics,
            )
    return ValidationResult(PASS, "serial log contains plausible configured TMP36 temperatures", metrics)


def read_serial_log_or_fail(paths: CasePaths) -> str:
    if paths.serial_log is None:
        raise SerialLogError("case does not define a serial log artifact")
    return read_serial_log(paths.serial_log)


def rounded(values: list[float], *, digits: int = 9) -> list[float]:
    return [round(value, digits) for value in values]


def rounded_scalar(value: float | None, *, digits: int = 9) -> float | None:
    return round(value, digits) if value is not None else None


__all__ = [
    "SerialLogError",
    "StaticCheckError",
    "VcdParseError",
    "validate_task",
    "validate_frequency_events",
]

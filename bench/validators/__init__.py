"""Reusable validator families for Arduino Mega Wokwi tasks."""

from __future__ import annotations

import re
from typing import Any

from bench.config import TaskConfig
from bench.results import FAIL, PASS, ValidationResult
from bench.runner import CasePaths
from bench.serial import (
    SerialLogError,
    count_occurrences,
    exact_count_sequence,
    extract_floats,
    extract_ints,
    monotonic_counter_reaches,
    read_serial_log,
)
from bench.static import StaticCheckError, validate_forbidden_calls, validate_static_checks
from bench.lcd1602 import (
    decode_lcd1602_vcd,
    decode_lcd1602_vcd_frames,
    frame_contains,
    frame_matches_regex,
    frame_metrics,
)
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
    if family not in VALIDATORS:
        return ValidationResult(FAIL, f"unknown validator family: {family}", base_metrics(task, paths))
    result = VALIDATORS[family](task, paths)
    merged = base_metrics(task, paths)
    merged.update(result.metrics)
    return ValidationResult(
        result.classification,
        result.reason,
        merged,
        failure_stage=result.failure_stage,
        failure_source=result.failure_source,
    )


def validate_composite(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    metrics: dict[str, Any] = {"checks": []}
    for index, check in enumerate(task.validator.get("checks", []), start=1):
        result = validate_check(task, paths, check)
        metrics["checks"].append(
            {
                "index": index,
                "family": check.get("family"),
                "classification": result.classification,
                "reason": result.reason,
                "metrics": result.metrics,
            }
        )
        if result.classification != PASS:
            return ValidationResult(result.classification, result.reason, metrics)
    return ValidationResult(PASS, "all composite validator checks passed", metrics)


def validate_check(task: TaskConfig, paths: CasePaths, check: dict[str, Any]) -> ValidationResult:
    proxy = TaskConfig(path=task.path, data={**task.data, "validator": check})
    family = check.get("family")
    if family not in COMPOSITE_CHECK_VALIDATORS:
        return ValidationResult(FAIL, f"unknown composite check family: {family}")
    return COMPOSITE_CHECK_VALIDATORS[family](proxy, paths)


def validate_static_patterns(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    checks = dict(task.static_checks)
    checks.update(task.validator_params())
    try:
        validate_static_checks(paths.sketch, checks, build_kind=task.board_profile.build_kind)
    except StaticCheckError as exc:
        return ValidationResult(FAIL, str(exc), {"static_check_passed": False})
    return ValidationResult(PASS, "static checks passed", {"static_check_passed": True})


def validate_serial_regex_sequence(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    text = read_serial_log_or_fail(paths)
    params = task.validator_params()
    patterns = list(params.get("patterns") or [])
    if not patterns:
        return ValidationResult(FAIL, "serial regex validator requires patterns")
    cursor = 0
    matches: list[dict[str, Any]] = []
    for pattern in patterns:
        match = re.search(pattern, text[cursor:], flags=re.MULTILINE | re.IGNORECASE)
        if not match:
            return ValidationResult(
                FAIL,
                f"serial log does not contain expected pattern in order: {pattern}",
                {"patterns": patterns, "matches": matches},
            )
        absolute_start = cursor + match.start()
        absolute_end = cursor + match.end()
        matches.append({"pattern": pattern, "text": match.group(0), "start": absolute_start})
        cursor = absolute_end
    return ValidationResult(PASS, "serial log contains expected regex sequence", {"patterns": patterns, "matches": matches})


def validate_serial_observation_sequence(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    text = read_serial_log_or_fail(paths)
    lines = nonempty_lines(text)
    observations = task.validator_params().get("observations") or []
    cursor = 0
    matches: list[dict[str, Any]] = []
    metrics = {"observations": observations, "matches": matches}
    for observation in observations:
        patterns = [str(pattern) for pattern in observation.get("patterns", [])]
        ranges = observation.get("numeric_ranges") or []
        found = None
        for index in range(cursor, len(lines)):
            line = lines[index]
            if not all(re.search(pattern, line, flags=re.IGNORECASE) for pattern in patterns):
                continue
            numbers = extract_floats(line)
            if ranges and not numeric_ranges_match(numbers, ranges):
                continue
            found = (index, line, numbers)
            break
        if found is None:
            return ValidationResult(
                FAIL,
                f"serial log is missing observation {observation.get('label')!r}",
                metrics,
            )
        cursor = found[0] + 1
        matches.append(
            {
                "label": observation.get("label"),
                "line": found[0] + 1,
                "text": found[1],
                "numbers": rounded(found[2], digits=3),
            }
        )
    return ValidationResult(PASS, "serial log contains configured observation sequence", metrics)


def numeric_ranges_match(numbers: list[float], ranges: list[list[float]]) -> bool:
    if len(numbers) < len(ranges):
        return False
    cursor = 0
    for bounds in ranges:
        match_index = None
        for index in range(cursor, len(numbers)):
            if float(bounds[0]) <= numbers[index] <= float(bounds[1]):
                match_index = index
                break
        if match_index is None:
            return False
        cursor = match_index + 1
    return True


def validate_serial_numeric_ranges(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    text = read_serial_log_or_fail(paths)
    params = task.validator_params()
    ranges = params.get("ranges") or []
    values = extract_floats(text)
    metrics = {"observed_numbers": values, "ranges": ranges}
    if len(values) < len(ranges):
        return ValidationResult(FAIL, "serial log does not contain enough numeric values", metrics)
    cursor = 0
    matched: list[float] = []
    for bounds in ranges:
        found = None
        for index in range(cursor, len(values)):
            if float(bounds[0]) <= values[index] <= float(bounds[1]):
                found = values[index]
                cursor = index + 1
                break
        if found is None:
            return ValidationResult(FAIL, f"serial log is missing numeric value in range {bounds}", metrics)
        matched.append(found)
    metrics["matched_numbers"] = matched
    return ValidationResult(PASS, "serial numeric ranges matched in order", metrics)


def validate_bme280_environment(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    text = read_serial_log_or_fail(paths)
    params = task.validator_params()
    variant = task.data.get("active_simulation_variant") or {}
    variant_attrs = next(iter((variant.get("attrs") or {}).values()), {})
    expected_temperature = params.get("expected_temperature_c")
    expected_humidity = params.get("expected_humidity_rh")
    if expected_temperature is None or expected_humidity is None:
        expected_temperature = variant_attrs.get("temperatureC", variant_attrs.get("temperature"))
        expected_humidity = variant_attrs.get("humidityRH", variant_attrs.get("humidity"))
    if expected_temperature is None or expected_humidity is None:
        return ValidationResult(FAIL, "BME280 validator requires expected temperature and humidity")
    expected_pressure = params.get("expected_pressure_pa")
    if expected_pressure is None:
        expected_pressure = variant_attrs.get("pressurePa")

    expected_temperature = float(expected_temperature)
    expected_humidity = float(expected_humidity)
    temp_tolerance = float(params.get("temperature_tolerance_c", 0.5))
    humidity_tolerance = float(params.get("humidity_tolerance_rh", 2.0))
    temperatures = labeled_serial_values(text, r"temp(?:erature)?")
    humidities = labeled_serial_values(text, r"hum(?:idity)?|relative\s+humidity|rh")
    metrics: dict[str, Any] = {
        "expected_temperature_c": expected_temperature,
        "expected_humidity_rh": expected_humidity,
        "temperature_tolerance_c": temp_tolerance,
        "humidity_tolerance_rh": humidity_tolerance,
        "observed_temperatures_c": rounded(temperatures, digits=3),
        "observed_humidities_rh": rounded(humidities, digits=3),
    }
    matching_temperature = first_within(temperatures, expected_temperature, temp_tolerance)
    if matching_temperature is None:
        return ValidationResult(
            FAIL,
            f"serial log is missing BME280 temperature near {expected_temperature:g}C",
            metrics,
        )
    matching_humidity = first_within(humidities, expected_humidity, humidity_tolerance)
    if matching_humidity is None:
        return ValidationResult(
            FAIL,
            f"serial log is missing BME280 humidity near {expected_humidity:g}% RH",
            metrics,
        )
    metrics["matched_temperature_c"] = round(matching_temperature, 3)
    metrics["matched_humidity_rh"] = round(matching_humidity, 3)

    if expected_pressure is not None:
        expected_pressure = float(expected_pressure)
        pressure_tolerance = float(params.get("pressure_tolerance_pa", 100.0))
        pressures = labeled_serial_values(text, r"press(?:ure)?")
        metrics["expected_pressure_pa"] = expected_pressure
        metrics["pressure_tolerance_pa"] = pressure_tolerance
        metrics["observed_pressures_pa"] = rounded(pressures, digits=3)
        matching_pressure = first_within(pressures, expected_pressure, pressure_tolerance)
        if matching_pressure is None:
            return ValidationResult(
                FAIL,
                f"serial log is missing BME280 pressure near {expected_pressure:g} Pa",
                metrics,
            )
        metrics["matched_pressure_pa"] = round(matching_pressure, 3)

    bus_activity = params.get("bus_activity")
    if bus_activity:
        bus_result = validate_bus_activity(
            TaskConfig(path=task.path, data={**task.data, "validator": {"family": "bus_activity", "params": bus_activity}}),
            paths,
        )
        metrics["bus_activity"] = bus_result.metrics
        if bus_result.classification != PASS:
            return ValidationResult(bus_result.classification, bus_result.reason, metrics)

    return ValidationResult(PASS, "serial log contains expected BME280 readings", metrics)


def labeled_serial_values(text: str, label_pattern: str) -> list[float]:
    pattern = re.compile(
        rf"(?:{label_pattern})\D*([-+]?\d+(?:\.\d+)?)",
        flags=re.IGNORECASE,
    )
    values: list[float] = []
    for match in pattern.finditer(text):
        raw = match.group(1)
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return values


def first_within(values: list[float], expected: float, tolerance: float) -> float | None:
    for value in values:
        if abs(value - expected) <= tolerance:
            return value
    return None


def validate_lcd_text(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    if paths.vcd is None:
        return ValidationResult(FAIL, "case does not define a VCD artifact")
    params = task.validator_params()
    frame = decode_lcd1602_vcd(paths.vcd, signals=params.get("signals"))
    metrics = frame_metrics(frame)
    expected = params.get("expected_texts") or params.get("expected_lines") or []
    expected_regexps = params.get("expected_regexps") or []
    metrics["expected_texts"] = expected
    metrics["expected_regexps"] = expected_regexps
    for item in expected:
        if not frame_contains(frame, str(item)):
            return ValidationResult(FAIL, f"LCD frame is missing expected text: {item}", metrics)
    for pattern in expected_regexps:
        if not frame_matches_regex(frame, str(pattern)):
            return ValidationResult(
                FAIL, f"LCD frame does not match expected pattern: {pattern}", metrics
            )
    return ValidationResult(PASS, "LCD frame contains expected text", metrics)


def validate_lcd_text_sequence(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    if paths.vcd is None:
        return ValidationResult(FAIL, "case does not define a VCD artifact")
    params = task.validator_params()
    frames = decode_lcd1602_vcd_frames(paths.vcd, signals=params.get("signals"))
    expected_frames = params.get("frames") or []
    cursor = 0
    matches: list[dict[str, Any]] = []
    metrics = {
        "frame_count": len(frames),
        "expected_frames": expected_frames,
        "matches": matches,
    }
    for expected in expected_frames:
        texts = [str(item) for item in expected.get("expected_texts", [])]
        regexps = [str(item) for item in expected.get("expected_regexps", [])]
        start_s = expected.get("start_s")
        end_s = expected.get("end_s")
        found = None
        for index in range(cursor, len(frames)):
            timed = frames[index]
            if start_s is not None and timed.timestamp_s < float(start_s):
                continue
            if end_s is not None and timed.timestamp_s > float(end_s):
                break
            if all(frame_contains(timed.frame, text) for text in texts) and all(
                frame_matches_regex(timed.frame, pattern) for pattern in regexps
            ):
                found = (index, timed)
                break
        if found is None:
            return ValidationResult(
                FAIL,
                "LCD frames are missing expected text sequence item: "
                f"{texts + regexps}",
                metrics,
            )
        cursor = found[0] + 1
        matches.append(
            {
                "expected_texts": texts,
                "expected_regexps": regexps,
                "timestamp_s": rounded_scalar(found[1].timestamp_s),
                **frame_metrics(found[1].frame),
            }
        )
    return ValidationResult(PASS, "LCD frames contain expected text sequence", metrics)


def validate_window_ratios(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    if paths.vcd is None:
        return ValidationResult(FAIL, "case does not define a VCD artifact")
    params = task.validator_params()
    signal = params.get("channel", "D0")
    events = parse_vcd_signal(paths.vcd, signal)
    windows = params.get("windows") or []
    if events and windows:
        max_end = max(float(window["end_s"]) for window in windows)
        if events[-1].timestamp_s < max_end:
            events = [*events, VcdEvent(max_end, events[-1].value)]
    segments = build_segments(events)
    ratios = []
    for window in windows:
        ratio = value_ratio(segments, float(window["start_s"]), float(window["end_s"]))
        ratios.append(ratio)
        bounds = window.get("ratio_range", [0.0, 1.0])
        if not in_range(ratio, bounds):
            return ValidationResult(
                FAIL,
                f"{signal} ratio {ratio:.3f} outside expected range {bounds}",
                {"ratios": rounded(ratios, digits=4), "windows": windows},
            )
    return ValidationResult(PASS, f"{signal} ratios matched configured windows", {"ratios": rounded(ratios, digits=4), "windows": windows})


def validate_frequency_windows(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    if paths.vcd is None:
        return ValidationResult(FAIL, "case does not define a VCD artifact")
    params = task.validator_params()
    signal = params.get("channel", "D0")
    events = parse_vcd_signal(paths.vcd, signal)
    metrics: dict[str, Any] = {"windows": []}
    for window in params.get("windows") or []:
        start = float(window["start_s"])
        end = float(window["end_s"])
        subset = [event for event in events if start <= event.timestamp_s <= end]
        transitions = max(0, len(subset) - 1)
        item = {"start_s": start, "end_s": end, "transitions": transitions}
        if window.get("inactive"):
            max_transitions = int(window.get("max_transitions", 1))
            item["max_transitions"] = max_transitions
            metrics["windows"].append(item)
            if transitions > max_transitions:
                return ValidationResult(FAIL, f"{signal} was active during inactive window", metrics)
            continue
        if len(subset) < 4:
            metrics["windows"].append(item)
            return ValidationResult(FAIL, f"{signal} has too few transitions in frequency window", metrics)
        local = [VcdEvent(event.timestamp_s - start, event.value) for event in subset]
        result = validate_frequency_events(local, window, signal)
        item.update(result.metrics)
        metrics["windows"].append(item)
        if result.classification != PASS:
            return ValidationResult(result.classification, result.reason, metrics)
    return ValidationResult(PASS, f"{signal} frequency windows matched expectations", metrics)


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


def validate_bus_activity(task: TaskConfig, paths: CasePaths) -> ValidationResult:
    if paths.vcd is None:
        return ValidationResult(FAIL, "case does not define a VCD artifact")
    params = task.validator_params()
    pins = [str(pin) for pin in params.get("pins", [])]
    min_transitions = int(params.get("min_transitions", 2))
    events_by_pin = parse_vcd_signals(paths.vcd, pins)
    metrics: dict[str, Any] = {
        "bus": params.get("bus"),
        "pins": {},
        "min_transitions": min_transitions,
    }
    for pin, events in events_by_pin.items():
        transitions = max(0, len(events) - 1)
        metrics["pins"][pin] = {"transitions": transitions}
        if transitions < min_transitions:
            return ValidationResult(
                FAIL,
                f"{params.get('bus')} pin {pin} has too few transitions",
                metrics,
            )
    return ValidationResult(PASS, f"{params.get('bus')} bus activity observed", metrics)


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
    skip_segments = int(params.get("skip_startup_segments", 1))
    if len(segments) < (min_cycles * 2 + skip_segments):
        return ValidationResult(
            FAIL,
            f"too few {signal} transitions for {min_cycles} post-startup cycles",
            metrics,
        )

    steady_segments = segments[skip_segments:]
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
    # A signal that is driven to a level and never transitions again has no closing
    # event, so its final level is not represented as a segment. Hold the last level
    # until the end of the latest analysis window so an output that stays asserted
    # until the end of the trace is measured correctly (mirrors validate_window_ratios).
    windows = list(params.get("active_windows_s", [])) + list(params.get("inactive_windows_s", []))
    if events and windows:
        max_end = max(float(window[1]) for window in windows)
        if events[-1].timestamp_s < max_end:
            events = [*events, VcdEvent(max_end, events[-1].value)]
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
    scenario = task.scenario or {}
    lines = nonempty_lines(text)
    metrics: dict[str, Any] = {
        "expected_texts": expected,
        "counts": {},
        "matching_lines": matching_serial_lines(lines, expected),
    }

    if scenario.get("family") == "button_press_sequence" and len(expected) == 1:
        expected_count = len(scenario.get("presses") or [])
        observed_count = count_matching_lines(lines, expected[0])
        metrics.update(
            {
                "scenario_family": "button_press_sequence",
                "expected_response_count": expected_count,
                "observed_response_count": observed_count,
                "stimulus_windows_ms": button_press_windows_ms(scenario),
            }
        )
        if observed_count != expected_count:
            return ValidationResult(
                FAIL,
                f"expected exactly {expected_count} serial response(s) for configured button presses, found {observed_count}",
                metrics,
            )
        return ValidationResult(PASS, "serial log matches configured button press response count", metrics)

    if scenario.get("family") == "pir_state_sequence":
        state_texts = params.get("state_texts") or {}
        expected_sequence = [
            state_texts.get(str(state.get("value")), state_texts.get(state.get("value")))
            for state in scenario.get("states", [])
        ]
        if expected_sequence and all(expected_sequence):
            observed_sequence = observed_text_sequence(lines, list(state_texts.values()))
            metrics.update(
                {
                    "scenario_family": "pir_state_sequence",
                    "expected_sequence": expected_sequence,
                    "observed_sequence": observed_sequence,
                    "stimulus_windows_ms": state_windows_ms(scenario, "states"),
                }
            )
            if observed_sequence != expected_sequence:
                return ValidationResult(
                    FAIL,
                    "serial log does not follow configured PIR state transition sequence",
                    metrics,
                )
            return ValidationResult(PASS, "serial log follows configured PIR state transitions", metrics)

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
    match_mode = str(params.get("match_mode", "monotonic_reaches"))
    allow_repeats = bool(params.get("allow_repeats", False))
    values = extract_ints(text)
    metrics = {"integers": values, "expected_count": expected_count, "match_mode": match_mode}
    if match_mode == "exact_sequence":
        if not exact_count_sequence(values, expected_count, allow_repeats=allow_repeats):
            return ValidationResult(
                FAIL,
                f"serial log does not show the exact count sequence 1..{expected_count}",
                metrics,
            )
        return ValidationResult(PASS, "serial log shows the exact count sequence", metrics)
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
    observations = numeric_line_observations(text)
    values = [value for _index, value, _line in observations]
    metrics = {
        "expected_celsius": expected,
        "observed_numbers": rounded(values, digits=3),
        "tolerance_celsius": tolerance,
        "ordered_matches": [],
    }
    if task.scenario and task.scenario.get("family") == "analog_position_sequence":
        metrics["scenario_positions"] = [item.get("value") for item in task.scenario.get("positions", [])]
        metrics["scenario_expected_celsius"] = rounded(
            [
                position_to_tmp36_celsius(float(item.get("value")), voltage=task.board_profile.voltage)
                for item in task.scenario.get("positions", [])
            ],
            digits=3,
        )

    start_index = 0
    matches: list[dict[str, Any]] = []
    for wanted in expected:
        match = next_ordered_temperature_match(observations, wanted, tolerance, start_index)
        if match is None:
            metrics["ordered_matches"] = matches
            return ValidationResult(
                FAIL,
                f"serial log does not contain ordered temperature observation near {wanted:g}C",
                metrics,
            )
        line_index, actual, line = match
        matches.append(
            {
                "line": line_index,
                "expected_celsius": round(wanted, 3),
                "observed_celsius": round(actual, 3),
                "text": line,
            }
        )
        start_index = line_index + 1
    metrics["ordered_matches"] = matches
    return ValidationResult(PASS, "serial log contains plausible configured TMP36 temperatures", metrics)


def read_serial_log_or_fail(paths: CasePaths) -> str:
    if paths.serial_log is None:
        raise SerialLogError("case does not define a serial log artifact")
    return read_serial_log(paths.serial_log)


def rounded(values: list[float], *, digits: int = 9) -> list[float]:
    return [round(value, digits) for value in values]


def rounded_scalar(value: float | None, *, digits: int = 9) -> float | None:
    return round(value, digits) if value is not None else None


def nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def serial_line_matches(line: str, expected: str, *, case_sensitive: bool = True) -> bool:
    haystack = line if case_sensitive else line.lower()
    needle = expected if case_sensitive else expected.lower()
    return haystack == needle or needle in haystack


def count_matching_lines(lines: list[str], expected: str, *, case_sensitive: bool = True) -> int:
    return sum(1 for line in lines if serial_line_matches(line, expected, case_sensitive=case_sensitive))


def matching_serial_lines(lines: list[str], expected: list[str]) -> list[str]:
    return [
        line
        for line in lines
        if any(serial_line_matches(line, item) for item in sorted(expected, key=len, reverse=True))
    ]


def observed_text_sequence(lines: list[str], expected_texts: list[str]) -> list[str]:
    ordered = sorted(expected_texts, key=len, reverse=True)
    observed: list[str] = []
    for line in lines:
        for expected in ordered:
            if serial_line_matches(line, expected):
                observed.append(expected)
                break
    return observed


def state_windows_ms(scenario: dict[str, Any], key: str) -> list[dict[str, Any]]:
    cursor = float(scenario.get("initial_delay_ms", 0))
    windows: list[dict[str, Any]] = []
    for item in scenario.get(key, []):
        duration = float(item.get("duration_ms", 0))
        windows.append({"value": item.get("value"), "start_ms": cursor, "end_ms": cursor + duration})
        cursor += duration
    return windows


def button_press_windows_ms(scenario: dict[str, Any]) -> list[dict[str, float]]:
    cursor = float(scenario.get("initial_delay_ms", 0))
    windows: list[dict[str, float]] = []
    for press in scenario.get("presses", []):
        duration = float(press.get("duration_ms", 200))
        windows.append({"start_ms": cursor, "end_ms": cursor + duration})
        cursor += duration + float(press.get("after_ms", 200))
    return windows


def numeric_line_observations(text: str) -> list[tuple[int, float, str]]:
    observations: list[tuple[int, float, str]] = []
    for index, line in enumerate(nonempty_lines(text), start=1):
        values = extract_floats(line)
        if len(values) == 1:
            observations.append((index, values[0], line))
    return observations


def next_ordered_temperature_match(
    observations: list[tuple[int, float, str]],
    wanted: float,
    tolerance: float,
    start_line: int,
) -> tuple[int, float, str] | None:
    for line_index, actual, line in observations:
        if line_index < start_line:
            continue
        if abs(actual - wanted) <= tolerance:
            return line_index, actual, line
    return None


def position_to_tmp36_celsius(position: float, *, voltage: float = 5.0) -> float:
    return ((position * voltage) - 0.5) * 100.0


# Top-level validator dispatch. Keys MUST stay in sync with
# bench.config.VALIDATOR_FAMILIES (enforced by tests/test_registry_consistency.py).
VALIDATORS = {
    "composite": validate_composite,
    "static_checks": validate_static_patterns,
    "serial_regex_sequence": validate_serial_regex_sequence,
    "serial_numeric_ranges": validate_serial_numeric_ranges,
    "bme280_environment": validate_bme280_environment,
    "lcd_text": validate_lcd_text,
    "window_ratios": validate_window_ratios,
    "frequency_windows": validate_frequency_windows,
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
    "serial_observation_sequence": validate_serial_observation_sequence,
    "bus_activity": validate_bus_activity,
    "lcd_text_sequence": validate_lcd_text_sequence,
}

# Families that may appear as a sub-check inside a `composite` validator. This is
# intentionally a subset of VALIDATORS: `composite` cannot nest itself, and the
# whole-trace waveform families (morse_sos, no_delay_static_plus_waveform,
# pwm_breathing) are not composable sub-checks.
COMPOSITE_CHECK_VALIDATORS = {
    family: VALIDATORS[family]
    for family in (
        "static_checks",
        "serial_regex_sequence",
        "serial_numeric_ranges",
        "bme280_environment",
        "lcd_text",
        "window_ratios",
        "frequency_windows",
        "waveform_frequency",
        "multi_channel_frequency",
        "stimulus_to_output",
        "serial_contains_on_stimulus",
        "serial_count_sequence",
        "debounce_serial",
        "analog_temperature_serial",
        "serial_observation_sequence",
        "bus_activity",
        "lcd_text_sequence",
    )
}


__all__ = [
    "SerialLogError",
    "StaticCheckError",
    "VcdParseError",
    "validate_task",
    "validate_frequency_events",
]

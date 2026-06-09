# LED Benchmark Cases

This workspace is organized around self-contained test cases. Each case owns the
sketch, simulator diagram, simulator config, VCD path, and build artifacts that
belong together.

## Layout

```text
cases/
  blink-1hz-wokwi-mega/
  blink-led-morse-code-wokwi-mega/
  blink-led-no-delay-wokwi-mega/
  breathing-led-wokwi-mega/
tools/
  blink_vcd_harness.py
  test_blink_led_morse_code.py
  test_blink_led_no_delay.py
  test_breathing_led.py
```

Each case contains:

```text
case.json
diagram.json
wokwi.toml
sketch/<sketch_name>/<sketch_name>.ino
sketch/<sketch_name>/sketch.yaml
artifacts/build/
artifacts/logic/wokwi.vcd
artifacts/archive/vcd/
```

`case.json` is the durable link between one task, one sketch, one diagram, and
one VCD. Future Wokwi or Renode tasks should be added as sibling folders under
`cases/`.

## Wokwi Mega Diagram

All current cases use the same duplicated Arduino Mega diagram:

- Arduino Mega: `wokwi-arduino-mega`
- Arduino CLI FQBN: `arduino:avr:mega`
- LED on GPIO 3 through a resistor
- Logic analyzer `D0` connected directly to GPIO 3
- Logic analyzer `GND` connected to board GND

The root `wokwi.toml` can point at one active case for the VS Code Wokwi
extension, but each case also has its own `wokwi.toml` and isolated artifact
paths.

## Build

Use the matching VS Code build task for a case:

```text
Build blink-1hz-wokwi-mega
Build blink-led-morse-code-wokwi-mega
Build blink-led-no-delay-wokwi-mega
Build breathing-led-wokwi-mega
```

Equivalent command shape:

```powershell
arduino-cli compile -e -b arduino:avr:mega `
  --build-path cases/<case-id>/artifacts/build `
  cases/<case-id>/sketch/<sketch-name>
```

## Simulate And Test

The Python validators now run the whole case by default: compile with
`arduino-cli`, run Wokwi headlessly with that case's `diagram.json` and
`wokwi.toml`, export a fresh logic-analyzer VCD, then validate it.

Each validator has a default case, so these no-argument commands are enough:

```powershell
python tools/blink_vcd_harness.py
python tools/test_blink_led_morse_code.py
python tools/test_blink_led_no_delay.py
python tools/test_breathing_led.py
```

You can also run a specific case explicitly:

```powershell
python tools/blink_vcd_harness.py --case cases/blink-1hz-wokwi-mega
python tools/test_blink_led_morse_code.py --case cases/blink-led-morse-code-wokwi-mega
python tools/test_blink_led_no_delay.py --case cases/blink-led-no-delay-wokwi-mega
python tools/test_breathing_led.py --case cases/breathing-led-wokwi-mega
```

The generated VCD is written inside that same case:

```text
cases/<case-id>/artifacts/logic/wokwi.vcd
```

Before a default run writes a new VCD, any existing current VCD is moved into
that case's archive:

```text
cases/<case-id>/artifacts/archive/vcd/<case-id>__<utc-timestamp>__wokwi.vcd
```

Keeping current and archived VCD files inside case folders prevents parallel
runs or repeated exports from overwriting other task results.

For parser/debug work with an existing VCD, add `--use-existing-vcd`:

```powershell
python tools/blink_vcd_harness.py --use-existing-vcd --case cases/blink-1hz-wokwi-mega
```

To validate an archived VCD, pass either an archive filename, path, or `latest`:

```powershell
python tools/blink_vcd_harness.py --case cases/blink-1hz-wokwi-mega --archived-vcd latest
```

Each validator prints JSON with exactly one top-level classification:

- `COMPILE_FAIL` - the submitted firmware could not be compiled
- `SIM_INFRA_FAIL` - simulator/tooling infrastructure failed, such as missing case metadata or unavailable Wokwi execution
- `SIM_OUTPUT_FAIL` - simulation ran far enough to expect output, but the VCD was missing, empty, or malformed
- `FAIL` - firmware ran, but `D0` did not show the expected behavior
- `PASS` - `D0` showed the expected behavior within tolerance

For compatibility with older tooling, the JSON also includes
`legacy_classification` using `CF`, `BF`, or `BC`, plus `failure_stage` for
analytics.

## Validator Regression Tests

The validator self-tests generate temporary synthetic cases and VCDs to prove
each grader can classify infrastructure/output failures, behavior failures, and
passing behavior without relying on hand-exported Wokwi traces:

```powershell
python -m unittest discover tests
```

These tests intentionally include both correct and incorrect waveforms. The
no-delay tests also include a blocking `delay()` sketch with an otherwise valid
waveform to verify the static check rejects obvious blocking implementations.

# IoT-Bench Arduino Mega Level 1 Harness

This repository uses the `bench` package as the only supported harness for the
Arduino Mega level-1 IoT-SkillsBench tasks. Task behavior lives in YAML; case
generation, Wokwi diagrams, scenarios, builds, live runs, artifact validation,
and result reporting are shared by task family.

The benchmark result contract is:

- `BC`: build/simulation/artifact generation succeeded and behavior passed.
- `BF`: build/simulation/artifact generation succeeded but behavior failed.
- `CF`: compile, Wokwi infrastructure, missing firmware, missing artifacts, or
  malformed artifacts prevented a trustworthy behavior judgment.

Detailed JSON still includes `classification`, `failure_stage`, `reason`, and
`metrics`, but the top-level `result` field is the benchmark outcome.

## Layout

```text
bench/
  cli.py              # generate/build/run/validate/doctor entry point
  config.py           # task YAML loading and family-aware validation
  diagrams.py         # deterministic Wokwi diagram families
  runner.py           # case generation, compile, Wokwi execution, verification
  scenarios.py        # Wokwi automation scenario generation
  serial.py           # serial-log parsing helpers
  static.py           # source-level checks such as forbidden delay()
  vcd.py              # VCD parsing and waveform analysis helpers
  validators/         # reusable validator families
tasks/arduino_mega/level1/
  *.yaml              # source of truth for task behavior
cases/
  <task>-wokwi-mega/  # generated Wokwi projects and reference sketches
```

Generated cases contain `case.yaml`, `case.json`, `diagram.json`,
`wokwi.toml`, a reference sketch, and artifact directories:

```text
artifacts/build/
artifacts/logic/
artifacts/serial/
artifacts/archive/vcd/
artifacts/archive/serial/
```

Stimulus-driven tasks also include `scenario.yaml`. Runtime build outputs,
VCDs, serial logs, archives, and verification manifests are generated locally
and are ignored by default.

## Workflow

Create a local Python environment and install the harness dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Check local tooling:

```powershell
python -m bench.cli doctor
```

Generate or refresh Wokwi projects:

```powershell
python -m bench.cli generate --task blink_led_1hz
python -m bench.cli generate --platform arduino_mega --level level1
```

Build sketches and create the firmware binaries referenced by `wokwi.toml`:

```powershell
python -m bench.cli build --task blink_led_1hz
python -m bench.cli build --platform arduino_mega --level level1
```

Run live Wokwi simulation, capture artifacts, validate behavior, and write
`artifacts/verification.json` after successful live runs:

```powershell
python -m bench.cli run --task blink_led_1hz
python -m bench.cli run --platform arduino_mega --level level1
```

Validate existing VCD or serial artifacts without compiling or running Wokwi:

```powershell
python -m bench.cli validate-artifacts --task blink_led_1hz --case cases/blink-1hz-wokwi-mega
python -m bench.cli validate-artifacts --task breathing_led --case cases/breathing-led-wokwi-mega --archived-vcd latest
```

Opening a generated case manually in Wokwi requires a prior `build`, because
`wokwi.toml` points at `artifacts/build/<sketch>.ino.hex` and
`artifacts/build/<sketch>.ino.elf`.

Validate a submitted sketch against a task:

```powershell
python -m bench.cli run --task button_status_count --sketch path/to/submission
python -m bench.cli validate-artifacts --task blink_led_no_delay --case cases/blink-led-no-delay-wokwi-mega --sketch path/to/submission
```

## Supported Tasks

- `blink_led_1hz`
- `blink_led_morse_code`
- `blink_led_no_delay`
- `blink_two_leds`
- `buzzer_doorbell`
- `button_status_display`
- `button_status_count`
- `button_press_debounce`
- `breathing_led`
- `sensor_pir_human_motion`
- `tmp36_read`

## Testing

Offline regression tests do not require Wokwi, network access, or a Wokwi token:

```powershell
python -m unittest discover tests
```

Live integration tests are opt-in and require `arduino-cli`, the Arduino AVR
platform, `wokwi-cli`, network access, and `WOKWI_CLI_TOKEN`:

```powershell
$env:RUN_WOKWI_INTEGRATION = "1"
python -m unittest discover tests
```

## Wokwi And Fixture Notes

- Build products, VCD captures, serial logs, archive snapshots, and
  verification manifests are local outputs. They include machine-specific
  details from Arduino and Wokwi runs, so regenerate them instead of committing
  them.
- `run` builds before simulation, so missing firmware binaries are reported as
  `CF` before Wokwi starts.
- Wokwi CLI runs depend on external infrastructure, token validity, and network
  availability. Use `doctor` when diagnosing environment failures.
- Wokwi scenario automation is treated as an isolated surface in
  `bench.scenarios`.
- Debounce uses a synthetic rapid press/release sequence with Wokwi button
  bounce disabled. This gives a stable benchmark oracle, not a full physical
  switch model.
- PIR is benchmarked as a controllable active-high digital input using part id
  `pir1`, because the Wokwi PIR part is not a reliable scenario-control oracle.
- TMP36 is benchmarked with a potentiometer analog source and the formula
  `C = (Vout - 0.5) * 100`; this checks TMP36-style conversion behavior, not a
  full sensor model.

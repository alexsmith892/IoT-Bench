# IoT-Bench Arduino Mega Harness

This repository currently implements the Arduino Mega portion of IoT-Bench.
The `bench` package is the only supported harness for these tasks. Task
behavior lives in YAML; case generation, Wokwi diagrams, scenarios, builds,
live runs, artifact validation, and result reporting are shared by task family.
Broader benchmark features such as multi-board support, generated scenario
suites, waveform-heavy peripheral analysis, fault injection, and public
leaderboard infrastructure are project goals, not completed repository
features unless they are explicitly represented in the code here.

The benchmark result contract is:

- `BC`: build/simulation/artifact generation succeeded and behavior passed.
- `BF`: build/simulation/artifact generation succeeded but behavior failed.
- `CF`: the submission's own source failed to compile. This is reserved for
  failures attributable to the model's code.
- `IF`: inconclusive / infrastructure. The harness could not obtain a
  trustworthy behavior judgment for reasons not clearly the submission's fault:
  Wokwi/simulator failures, environment or token problems, harness errors,
  unsupported/manual tasks, or missing/empty/malformed artifacts. `IF` results
  should be retried or excluded from scoring and must never be charged against
  the model.

Detailed JSON still includes `classification`, `failure_stage`,
`failure_source`, `reason`, and `metrics`, so any consumer can disambiguate the
precise cause behind an `IF` (e.g. `failure_source` of `simulator`,
`environment`, `harness`, or `artifact`). The top-level `result` field is the
benchmark outcome.

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
tasks/arduino_mega/level*/
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
artifacts/submissions/
artifacts/variants/
```

Stimulus-driven tasks also include `scenario.yaml`. Runtime build outputs,
VCDs, serial logs, archives, submission copies/builds, variant outputs, and
verification manifests are generated locally and are ignored by default.

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
python -m bench.cli generate --platform arduino_mega --level level2
python -m bench.cli generate --platform arduino_mega --level level3
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
python -m bench.cli run --platform arduino_mega --level level2 --regenerate
python -m bench.cli run --platform arduino_mega --level level3 --regenerate
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

## Task Coverage

Level 1:
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

Level 2 live-supported:
- `lcd1602_display_hello_world`
- `dht11_read`
- `ds1307_rtc`
- `mpu6050_read_i2c`
- `tilt_detection_alarm`
- `photoresistor_nightlight`
- `ds18b20_heat_alarm`
- `clap_switch`
- `hcsr501_motion_alarm`
- `hcsr04_find_distance`
- `parking_sensor`
- `reverse_parking_sensor`
- `rotary_encoder` (surrogate: dual digital-source quadrature injection)
- `16key_keypad` (surrogate: matrix cross-point switches)
- `bme280_read_i2c` (custom deterministic BME280 chip; multi-variant)
- `bme280_read_spi` (custom deterministic BME280 chip; multi-variant)

Level 3 live-supported:
- `dht11_read_button_display`
- `mpu6050_read_button_display`
- `mpu6050_read_periodic_display`
- `lcd1602_auto_brightness_control`
- `buzzer_toggle_led_freq`
- `tmp36_read_button_display`
- `tmp36_read_periodic_display`
- `reaction_timer_display`
- `sensor_water_level_display`
- `buzzer_laser_tripwire`
- `joystick_buzzer_pitch`
- `safebox` (surrogate: matrix keypad; wrong-then-correct relay windows)
- `safebox_display` (surrogate: matrix keypad; LCD + relay windows)
- `step_counter_print` (native MPU6050 acceleration controls)

## Shared Families

- `composite` fixtures assemble reusable Wokwi components from YAML instead of
  adding task-specific diagram code.
- `timeline` scenarios provide generic ordered delays and `set-control` events.
- `control_sequence` scenarios drive documented Wokwi part controls such as
  DHT temperature/humidity, DS18B20 temperature, photoresistor lux, and joystick
  axes.
- `composite` validators combine static, serial, LCD, waveform, frequency, and
  window-ratio checks for multi-part tasks.
- LCD1602 displays are validated by decoding the 4-bit parallel bus from VCD.
- LCD sequence validators can match intermediate frames instead of only the
  final display state.
- Static checks support forbidden calls, required regex patterns, and
  "any-of" required pattern groups.

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

- Build products, VCD captures, serial logs, archive snapshots, submission
  copies/builds, variant outputs, and verification manifests are local outputs.
  They include machine-specific details from Arduino and Wokwi runs, so
  regenerate them instead of committing them.
- `run` builds before simulation. A genuine compile failure of the submission
  is reported as `CF`; missing firmware binaries after a successful compile are
  an artifact problem and reported as `IF` before Wokwi starts.
- Wokwi CLI runs depend on external infrastructure, token validity, and network
  availability. Use `doctor` when diagnosing environment failures.
- Wokwi scenario automation is treated as an isolated surface in
  `bench.scenarios`.
- Tasks with `support.status: unsupported` or `manual` are reported as `IF`
  with a harness reason. They are skipped by bulk `generate` and `lint` so
  invalid diagrams are not mistaken for live benchmark cases.
- Debounce uses a synthetic rapid press/release sequence with Wokwi button
  bounce disabled. This gives a stable benchmark oracle, not a full physical
  switch model.
- PIR is benchmarked as a controllable active-high digital input using part id
  `pir1`, because the Wokwi PIR part is not a reliable scenario-control oracle.
- TMP36 is benchmarked with a potentiometer analog source and the formula
  `C = (Vout - 0.5) * 100`; this checks TMP36-style conversion behavior, not a
  full sensor model.
- DHT11 tasks use Wokwi's DHT22 component as a deterministic DHT-family
  surrogate because Wokwi does not expose a distinct DHT11 part.
- BME280 I2C/SPI tasks are live-supported through the deterministic custom
  `chip-bme280` model in `bench/chips/bme280`; Wokwi does not provide a native
  BME280 part. The custom model is a benchmark peripheral, not a complete
  physical BME280 emulator. Temperature, humidity, and pressure are all scored
  per simulation variant (`expected_temperature_c`, `expected_humidity_rh`,
  `expected_pressure_pa`).
- DS1307 validation focuses on the RTC date/time contract. The upstream wording
  mentions temperature data, but Wokwi's DS1307 model does not provide a
  trustworthy temperature observable for this harness.
- Photoresistor and joystick tasks use native Wokwi parts with scenario-driven
  controls. Water-level, laser-block, sound, shock, tilt, and some motion/input
  tasks use controllable potentiometer or pushbutton surrogates when Wokwi lacks
  a scenario-controllable physical module.
- Logic analyzer channel names in YAML use Wokwi pins `D0`, `D1`, etc. The
  semantic meaning is documented by the connected component and validator.
- Keypad tasks (`16key_keypad`, `safebox`, `safebox_display`) use `matrix_key`
  surrogates: a pushbutton bridges one row net and one column net, so each key is
  electrically identical to a real non-diode matrix key under a column-drive /
  row-read scan (including ghosting). The native `wokwi-membrane-keypad` exposes
  no automation control (wokwi-cli issue #10), so it cannot be driven live.
- `rotary_encoder` uses two `digital_pullup` surrogates (active-low, idle HIGH)
  on the CLK/DT pins. A `control_sequence` steps them through a clean Gray-code
  sequence (one bit per step); the native `wokwi-ky-040` has no automation
  control. As with all fixed-stimulus serial oracles, the reference scenario is
  deterministic but the printed sequence is known, so pair it with code review
  when a hard-coded submission is a concern.
- `step_counter_print` is fully native: the Wokwi MPU6050 exposes `accelX/Y/Z`
  automation controls, so a `control_sequence` injects a baseline-then-spike
  acceleration profile and the firmware threshold-counts the spikes.

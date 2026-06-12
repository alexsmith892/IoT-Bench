# IoT-Bench Harness

This repository implements the simulation-based IoT-Bench harness. The
`bench` package is the only supported harness for these tasks. Task behavior
lives in YAML; case generation, platform fixtures, scenarios, builds, live
runs, artifact validation, batch evaluation, and result reporting are shared
by task family across three platforms and two simulator backends:

| Platform | Board | Build | Simulator |
|---|---|---|---|
| `arduino_mega` | Arduino Mega (AVR) | arduino-cli | Wokwi (wokwi-cli) |
| `esp32s3_espidf` | ESP32-S3 DevKitC (ESP-IDF) | idf.py | Wokwi (wokwi-cli) |
| `zephyr_nano33ble` | Arduino Nano 33 BLE (nRF52840, Zephyr) | west | Renode (headless) |

Waveform-heavy peripheral analysis, fault injection, and the public
leaderboard frontend are project goals, not completed repository features
unless they are explicitly represented in the code here.

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
  cli.py              # generate/prompt/build/lint/doctor/run/evaluate/
                      # repeatability/validate-artifacts entry point
  config.py           # task YAML loading and family-aware validation
  diagrams.py         # deterministic Wokwi diagram families + control allowlist
  runner.py           # case generation, compile, Wokwi execution, variants,
                      # provenance manifests
  scenarios.py        # Wokwi automation scenario generation
  serial.py           # serial-log parsing helpers
  static.py           # source-level checks (required/forbidden patterns)
  vcd.py              # VCD parsing and waveform analysis helpers
  lcd1602.py          # LCD1602 4-bit bus decoding from VCD
  validators/         # reusable validator families
  chips/bme280/       # deterministic custom Wokwi chip for BME280 tasks
  tool_versions.yaml  # pinned arduino-cli / idf.py / wokwi-cli versions
tasks/arduino_mega/level*/
  *.yaml              # source of truth for task oracles (the answer key)
  *.prompt.md         # frozen model-facing task statement (one per task)
cases/
  <task>-wokwi-mega/  # generated Wokwi projects and reference sketches
tests/
  adversarial/        # known cheat stubs per task (regression corpus)
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

Stimulus-driven tasks also include `scenario.yaml`; tasks whose variants
override the stimulus additionally get
`artifacts/variants/<id>/scenario.yaml`. Runtime build outputs, VCDs, serial
logs, archives, submission copies/builds, variant outputs, and verification
manifests are generated locally and are ignored by default.

## Task Prompts And The Information Boundary

Each task has a frozen, model-facing specification in
`tasks/.../<task_id>.prompt.md` (print it with `python -m bench.cli prompt
--task <id>`). The prompt is the *only* task material a model under test may
see. The task YAML is the answer key: it contains the variant stimulus values,
scenario timings, and expected numeric bands that make the oracles
hardcode-resistant. Showing the YAML (or generated `scenario.yaml` /
`diagram.json` attrs) to a model under test invalidates the result.

Every prompt ends with the benchmark's library policy: submissions must use
only the Arduino core and its built-in libraries (`Wire`, `SPI`, `Serial`,
bundled core libraries) and communicate with sensors directly. This is what
makes the source-level static gates (e.g. requiring `Wire.requestFrom` in the
submission) fair: third-party driver libraries are disallowed by rule, so
their absence in a submission's source is a legitimate behavior failure.

## Anti-Gaming Oracles

Pass/fail is designed so that a hardcoded-output submission cannot pass:

- **Simulation variants** (`simulation_variants` in task YAML) run the same
  firmware against multiple configurations. Variants can override component
  attrs (e.g. a different seeded RTC time or sensor value per run) and/or
  declare a full replacement `scenario:` (a different stimulus timeline per
  run). Expected outputs differ per variant, so output that is constant across
  variants fails.
- `simulation.require_distinct_variant_outputs: true` additionally rejects
  submissions whose serial output is identical across variants (text and,
  where numbers are emitted, numeric values).
- **Stimulus correlation**: scenario-driven oracles check that output tracks
  injected stimulus (exact debounced-press counts, PIR state-transition order,
  step-count sequences, accelerometer raw counts matching injected values, LCD
  frames showing sensor values before and after a mid-run change).
- **Numeric display assertions**: `lcd_text` / `lcd_text_sequence` accept
  `expected_regexps` (per frame for the sequence form) so LCD oracles check
  values, not just labels.
- **Static gates**: source-level required patterns (real I2C read path,
  `digitalRead`, `millis`, ...) reject print-only stubs before simulation.
- **Adversarial regression corpus**: `tests/adversarial/<task_id>/*.ino` holds
  known cheat stubs for previously weak tasks. `tests/test_adversarial_static.py`
  pins which stubs the static gate must reject and which intentionally pass it
  (decoy stubs, rejected at runtime by the variant oracles — verified by live
  swap runs). Reference solutions for all hardened tasks have been verified BC
  live, and every stub verified BF live.
- **Provenance**: `artifacts/verification.json` records hashes for sketch,
  diagram, scenario, firmware, per-variant diagrams/scenarios, and outputs,
  plus tool versions. `validate-artifacts` refuses artifacts that do not match
  (-> `IF`), so results cannot be produced from tampered inputs unnoticed.

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
python -m bench.cli doctor --platform esp32s3_espidf
python -m bench.cli doctor --platform zephyr_nano33ble
```

Generate or refresh Wokwi projects:

```powershell
python -m bench.cli generate --task blink_led_1hz
python -m bench.cli generate --platform arduino_mega --level level1
python -m bench.cli generate --platform arduino_mega --level level2
python -m bench.cli generate --platform arduino_mega --level level3
python -m bench.cli generate --platform esp32s3_espidf --level level1
python -m bench.cli generate --platform zephyr_nano33ble --level level1
```

Build sketches and create the firmware binaries referenced by `wokwi.toml`:

```powershell
python -m bench.cli build --task blink_led_1hz
python -m bench.cli build --platform arduino_mega --level level1
python -m bench.cli build --platform esp32s3_espidf --level level1
```

Run live Wokwi simulation, capture artifacts, validate behavior, and write
`artifacts/verification.json` after successful live runs:

```powershell
python -m bench.cli run --task blink_led_1hz
python -m bench.cli run --platform arduino_mega --level level1
python -m bench.cli run --platform arduino_mega --level level2 --regenerate
python -m bench.cli run --platform arduino_mega --level level3 --regenerate
python -m bench.cli run --platform esp32s3_espidf --task blink_led_1hz --regenerate
python -m bench.cli run --platform zephyr_nano33ble --level level1
```

Validate existing VCD or serial artifacts without compiling or running Wokwi:

```powershell
python -m bench.cli validate-artifacts --task blink_led_1hz --case cases/blink-1hz-wokwi-mega
python -m bench.cli validate-artifacts --task breathing_led --case cases/breathing-led-wokwi-mega --archived-vcd latest
```

Opening a generated case manually in Wokwi requires a prior `build`, because
Arduino `wokwi.toml` files point at `artifacts/build/<sketch>.ino.hex` and
`artifacts/build/<sketch>.ino.elf`, while ESP-IDF cases point at
`artifacts/build/flasher_args.json` and `artifacts/build/<project>.elf`.

Validate a submitted sketch against a task:

```powershell
python -m bench.cli run --task button_status_count --sketch path/to/submission
python -m bench.cli validate-artifacts --task blink_led_no_delay --case cases/blink-led-no-delay-wokwi-mega --sketch path/to/submission
```

Batch-evaluate a directory of submissions (one sketch per task) into JSONL,
with automatic retry of `IF` results:

```powershell
python -m bench.cli evaluate --sketch-dir path/to/submissions --output results.jsonl --if-retries 1
```

Measure live repeatability of the reference sketches (flake census — any task
that flakes here is a leaderboard noise source):

```powershell
python -m bench.cli repeatability --runs 10 --output flakes.jsonl
```

Both commands enforce the pinned tool versions in `bench/tool_versions.yaml`
(override with `--allow-tool-version-mismatch`), so a Wokwi, arduino-cli, or
idf.py behavior change surfaces as an environment problem instead of silently
shifting behavior judgments.

## Task Coverage

Level 1:
- `blink_led_1hz`
- `blink_led_morse_code`
- `blink_led_no_delay`
- `blink_two_leds`
- `buzzer_doorbell`
- `button_status_display`
- `button_status_count`
- `button_press_debounce` (multi-variant: 2 vs 3 bounced presses)
- `breathing_led`
- `sensor_pir_human_motion` (multi-variant: different motion patterns)
- `tmp36_read`

Level 2 live-supported:
- `lcd1602_display_hello_world`
- `dht11_read`
- `ds1307_rtc` (multi-variant: different seeded clock per run)
- `mpu6050_read_i2c` (multi-variant: per-variant accel/gyro injection, raw-count oracle)
- `tilt_detection_alarm`
- `photoresistor_nightlight`
- `ds18b20_heat_alarm`
- `clap_switch`
- `hcsr501_motion_alarm`
- `hcsr04_find_distance` (multi-variant: different configured distances)
- `parking_sensor`
- `reverse_parking_sensor`
- `rotary_encoder` (surrogate: dual digital-source quadrature injection)
- `16key_keypad` (surrogate: matrix cross-point switches)
- `bme280_read_i2c` (custom deterministic BME280 chip; multi-variant)
- `bme280_read_spi` (custom deterministic BME280 chip; multi-variant)

Zephyr / Nano 33 BLE (Renode) level 1, all live-verified (reference BC across
variants, adversarial stubs BF):
- `blink_led_1hz`
- `blink_led_no_delay`
- `button_status_count` (multi-variant: 3 vs 4 presses)
- `button_press_debounce` (multi-variant: 2 vs 3 bounced presses)
- `sensor_pir_human_motion` (multi-variant: single vs double motion)

Zephyr / Nano 33 BLE (Renode) level 2, all live-verified:
- `ds1307_rtc` (custom C# DS1307 model compiled by Renode at include time;
  multi-variant seeded clock via per-variant attrs)
- `lsm9ds1_read_i2c` (native Renode LSM9DS1 — the board's real IMU; per-variant
  mid-run accel/gyro injection, raw-count oracle at 16384 LSB/g, 120 LSB/dps,
  verified live)
- `lcd1602_display_hello_world` (bit-banged 4-bit bus decoded from the
  synthesized VCD by the existing `lcd1602.py`)

Level 3 live-supported (the display tasks below are multi-variant with
numeric LCD oracles tied to injected stimulus):
- `dht11_read_button_display` (mid-run DHT value change between button reads)
- `mpu6050_read_button_display` (per-variant accel/gyro injection)
- `mpu6050_read_periodic_display` (per-variant accel/gyro injection)
- `lcd1602_auto_brightness_control`
- `buzzer_toggle_led_freq`
- `tmp36_read_button_display` (per-variant seeded ADC value)
- `tmp36_read_periodic_display` (mid-run analog change; counter + value frames)
- `reaction_timer_display` (per-variant button->shock gap; displayed ms must
  fall in the matching band)
- `sensor_water_level_display`
- `buzzer_laser_tripwire`
- `joystick_buzzer_pitch`
- `safebox` (surrogate: matrix keypad; wrong-then-correct relay windows)
- `safebox_display` (surrogate: matrix keypad; LCD must echo the
  variant-specific wrong code before Success; relay windows)
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
  final display state, with optional `start_s`/`end_s` time windows and
  `expected_regexps` for numeric content.
- Static checks support forbidden calls, required regex patterns, and
  "any-of" required pattern groups (comments and string literals are stripped
  before matching).
- Simulation variants deep-merge per-variant validator params into the base
  validator (positionally for `checks` lists — the `- {}` placeholder idiom)
  and may replace the scenario wholesale; variant scenarios are linted with
  the same structure/budget/control-allowlist rules as the base.

## Testing

Offline regression tests do not require Wokwi, network access, or a Wokwi token:

```powershell
python -m unittest discover tests
```

The offline suite includes the lint gates (variant ids, simulation budgets,
scenario-control allowlist, registry consistency) and the adversarial
static-gate expectations; it runs in CI on every push
(`.github/workflows/ci.yml`).

Live integration tests are opt-in. Arduino Mega tests require `arduino-cli`,
the Arduino AVR platform, `wokwi-cli`, network access, and `WOKWI_CLI_TOKEN`;
ESP32-S3 ESP-IDF tests require `idf.py`, `wokwi-cli`, network access, and
`WOKWI_CLI_TOKEN`:

```powershell
$env:RUN_WOKWI_INTEGRATION = "1"
python -m unittest discover tests
```

## Zephyr / Renode Platform Notes

The `zephyr_nano33ble` platform evaluates Zephyr RTOS firmware for the
Arduino Nano 33 BLE (nRF52840) in Renode instead of Wokwi, behind the same
task schema, validators, variant machinery, and result contract. The board
matches the upstream iot-skillsbench real-hardware target. Key facts
(live-verified details in `docs/renode-spike.md`):

- Cases get a generated `case.repl` (platform description: nRF52840 + probe
  LEDs on observed GPIO pins + `Miscellaneous.Button` drivers for scenario
  inputs) and `case.resc` (timed monitor script) instead of `diagram.json` /
  `wokwi.toml`. Scenario YAML families are shared; delays become
  `emulation RunFor` steps in exact virtual time, so stimulus timing is
  deterministic (two runs produce byte-identical artifacts).
- The logic-analyzer VCD is synthesized by an embedded IronPython hook that
  records GPIO transitions with microsecond virtual timestamps; `vcd.py`,
  the waveform validators, and (eventually) the LCD1602 decoder consume it
  unchanged. Serial output is the UART captured to a file; the Zephyr boot
  banner is disabled (`CONFIG_BOOT_BANNER=n`) so numeric serial oracles see
  only firmware output.
- Zephyr builds run through `west` from a staged, space-free directory
  (Zephyr's kconfig.cmake cannot handle spaces in application paths, and
  this repo's path contains one). The harness owns `CMakeLists.txt` and
  `prj.conf`; submissions are a single `src/main.c` (or an app directory,
  whose build config is replaced by the harness copy). CMake configure
  failures are environment problems (`IF`); only the compile step is
  charged as `CF`.
- `RENODE_PERIPHERAL_CONTROLS` is the scenario-control allowlist for this
  backend, linted like `PART_TYPE_CONTROLS`
  (`tests/test_renode_scenario_lint.py`). Per-variant scenario overrides are
  supported; per-variant `attrs` are rejected until the backend has
  peripheral models whose state variants can seed.
- The case `.repl` pins the CPU at 2 MIPS: busy-polling firmware
  (`k_uptime_get` loops) crosses the emulator/peripheral boundary on every
  RTC read and would otherwise simulate slower than the wall-clock guard;
  2 MIPS keeps polling at ~100 µs resolution with Zephyr boot under 3 ms of
  virtual time. Sleep-based firmware is unaffected.
- Sensor parts: scenario controls and per-variant `attrs` keep the Wokwi
  vocabulary (`accelX` in g, `rotationX` in deg/s, `initTime` ISO-8601) and
  are emitted as Renode property sets on the part (`twi0.imu1 AccelerationX
  0.5`), so the same injection/oracle design carries over. The IMU task uses
  Renode's native LSM9DS1 (the Nano 33 BLE's actual sensor) instead of a
  custom MPU6050; the DS1307 is an IoT-Bench C# model
  (`bench/chips/ds1307/DS1307.cs`) that Renode compiles at include time —
  it implements the read path of the contract and ignores writes to the
  timekeeping registers (read-and-print contract, like the Wokwi task).
  Zephyr's I2C drivers default to TWIM (EasyDMA), which Renode's nRF52840
  I2C model does not implement; the harness-owned `app.overlay` pins the
  legacy `nordic,nrf-twi` driver (verified live).
- Renode's stock nRF52840 model has no PWM or SAADC peripherals, so
  hardware-PWM (breathing LED) and analog tasks (TMP36 and the other
  potentiometer surrogates) need custom C# models before they can join this
  platform — that is the next backend milestone; DHT11 and HC-SR04 stay
  Wokwi-only (bit-banged microsecond protocols). The model fetches its SVD
  (register names for log messages) from a URL on first run and caches it
  afterwards.

Pinned tools for this platform (`bench/tool_versions.yaml`): the Renode
version, west version, and the Zephyr tree revision. `doctor --platform
zephyr_nano33ble` checks Renode, west, the workspace, and cmake/ninja (which
are often missing from non-interactive PATH on Windows; the harness finds
them in their default install locations).

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
- TMP36 (and the other analog surrogates: water-level, photoresistor
  brightness source, etc.) is a `wokwi-potentiometer` part. The diagram attr
  `value` is the raw ADC reading directly (`value: "153"` -> `analogRead`
  returns 153) and the scenario control `position` is normalized 0..1
  (raw ~ position x 1023). The oracle checks TMP36-style conversion
  (`C = (Vout - 0.5) * 100` at 5 V / 1023 counts), not a full sensor model.
  These constants are AVR-specific and must come from a board profile when
  ESP32 (3.3 V / 4095) is added.
- DHT11 tasks use Wokwi's DHT22 component as a deterministic DHT-family
  surrogate because Wokwi does not expose a distinct DHT11 part.
- BME280 I2C/SPI tasks are live-supported through the deterministic custom
  `chip-bme280` model in `bench/chips/bme280`; Wokwi does not provide a native
  BME280 part. The custom model is a benchmark peripheral, not a complete
  physical BME280 emulator. Temperature, humidity, and pressure are all scored
  per simulation variant (`expected_temperature_c`, `expected_humidity_rh`,
  `expected_pressure_pa`).
- DS1307 validation focuses on the read-and-print RTC contract: the prompt
  tells the model the clock is pre-seeded and must not be set, and each
  simulation variant seeds a different `initTime` (honored per-variant by
  Wokwi), so a hardcoded date/time string fails. Wokwi's DS1307 model
  provides no trustworthy temperature observable, so none is scored.
- MPU6050 automation controls take physical units (`accelX/Y/Z` in g,
  `rotationX/Y/Z` in deg/s) and the part reports raw counts at power-on
  default ranges: 16384 LSB/g and 131 LSB/(deg/s), verified live (0.5 g ->
  exactly 8192). Oracles bake in these defaults, and the prompts' library
  policy implies submissions must not reconfigure the sensor ranges.
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

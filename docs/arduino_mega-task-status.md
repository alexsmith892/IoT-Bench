# Arduino Mega Task Status

This page tracks `arduino_mega` maturity using the same evidence contract as the
ESP32-S3 path: a task is leaderboard-grade only with fresh, provenance-backed
`BC` evidence produced under the *current* scoring harness.

`cases/*/artifacts/verification.json` is local evidence (ignored by Git): useful
for `validate-artifacts` triage, not portable proof. The portable, tracked
summary is the evidence index, `docs/arduino_mega-evidence.json`.

## Readiness summary

**As of the 2026-06-18 live refresh + freeze, Arduino Mega is leaderboard-ready.**

- All **41** supported tasks (11 level-1 / 16 level-2 / 14 level-3) were rebuilt
  and re-simulated live with `--regenerate` against current sources and every
  one returned `BC`.
- Tool versions (from `doctor --platform arduino_mega`):
  `arduino-cli  Version: 1.5.1 Commit: 01f3d4f2b`, `wokwi-cli 0.26.1 (9d71b975b7eb)`.
  These match pinned `bench/tool_versions.yaml`.
- Build sweep: **41 BC / 0 BF / 0 CF / 0 IF**.
- Strict `validate-artifacts` (no bypass flags, full provenance + harness-hash
  check): **41 BC / 0 BF / 0 CF / 0 IF**.
- Evidence index `docs/arduino_mega-evidence.json`: `present: 41`, `missing: 0`,
  `fresh_bc: 41`, `stale: 0`, `publishable: 41`; every task `fresh` with
  `harness_match: true` and `result == BC`.
- Repeatability (3 runs each on the most stimulus/timing-sensitive tasks —
  `button_press_debounce`, `clap_switch`, `rotary_encoder`,
  `lcd1602_display_hello_world`, `hcsr04_find_distance`, `reaction_timer_display`,
  `step_counter_print`): **0 flaky**, every run `BC`.
- Full offline suite (`python -m unittest discover tests`): **315 tests OK**
  (12 live-integration skips). No residual non-Arduino blocker — the previously
  noted Zephyr Renode `.repl` regen drift is resolved on `main`.

`publishable` is the leaderboard-grade gate: fresh `BC` under the current harness
(`harness_match`). Readiness requires `publishable == total`, which forces a
fresh live sweep after any `bench/` harness edit (the benchmark harness hash
covers all `bench/**/*.py`). Re-freeze after any task/prompt/reference or harness
edit by re-running the live refresh below and `evidence-index`.

## Status matrix

All 41 tasks are fresh `BC` under the current harness.

### Level 1
| Task | Result | Fresh |
|---|---|---|
| `blink_led_1hz` | BC | yes |
| `blink_led_morse_code` | BC | yes |
| `blink_led_no_delay` | BC | yes |
| `blink_two_leds` | BC | yes |
| `breathing_led` | BC | yes |
| `button_press_debounce` | BC | yes |
| `button_status_count` | BC | yes |
| `button_status_display` | BC | yes |
| `buzzer_doorbell` | BC | yes |
| `sensor_pir_human_motion` | BC | yes |
| `tmp36_read` | BC | yes |

### Level 2
| Task | Result | Fresh |
|---|---|---|
| `16key_keypad` | BC | yes |
| `bme280_read_i2c` | BC | yes |
| `bme280_read_spi` | BC | yes |
| `clap_switch` | BC | yes |
| `dht11_read` | BC | yes |
| `ds1307_rtc` | BC | yes |
| `ds18b20_heat_alarm` | BC | yes |
| `hcsr04_find_distance` | BC | yes |
| `hcsr501_motion_alarm` | BC | yes |
| `lcd1602_display_hello_world` | BC | yes |
| `mpu6050_read_i2c` | BC | yes |
| `parking_sensor` | BC | yes |
| `photoresistor_nightlight` | BC | yes |
| `reverse_parking_sensor` | BC | yes |
| `rotary_encoder` | BC | yes |
| `tilt_detection_alarm` | BC | yes |

### Level 3
| Task | Result | Fresh |
|---|---|---|
| `buzzer_laser_tripwire` | BC | yes |
| `buzzer_toggle_led_freq` | BC | yes |
| `dht11_read_button_display` | BC | yes |
| `joystick_buzzer_pitch` | BC | yes |
| `lcd1602_auto_brightness_control` | BC | yes |
| `mpu6050_read_button_display` | BC | yes |
| `mpu6050_read_periodic_display` | BC | yes |
| `reaction_timer_display` | BC | yes |
| `safebox` | BC | yes |
| `safebox_display` | BC | yes |
| `sensor_water_level_display` | BC | yes |
| `step_counter_print` | BC | yes |
| `tmp36_read_button_display` | BC | yes |
| `tmp36_read_periodic_display` | BC | yes |

## Reference-sketch generation contract

Level-2/3 Arduino sketches are regenerated from `bench/runner.py` templates and
pinned to the committed `.ino` by
`tests/test_reference_sketch_consistency.py::test_committed_level2_3_sketches_match_templates`.

Level-1 sketches are **hand-authored**, not template-generated. Three of them
(`blink_led_morse_code`, `blink_led_no_delay`, `breathing_led`) have no template
at all. To prevent a deleted/regenerated level-1 case from silently building an
empty `setup/loop` stub:

- `bench.runner.example_sketch` now **raises** for an `arduino_mega` task with no
  template (instead of returning an empty stub).
- `bench.runner.arduino_reference_source` reproduces the committed level-1 sketch
  when there is no template, so regeneration into any root is deterministic.
- `tests/test_reference_sketch_consistency.py::test_every_arduino_task_has_a_nontrivial_committed_sketch`
  asserts every supported `arduino_mega` task ships a non-trivial committed
  `.ino`.

## Verification workflow

Fast offline checks (no Wokwi/network):

```powershell
python -m bench.cli doctor --platform arduino_mega
python -m bench.cli lint --platform arduino_mega --level all
python -m unittest discover tests
```

Live refresh / leaderboard freeze (needs `WOKWI_CLI_TOKEN` + network; run with
the shell sandbox disabled):

```powershell
python -m bench.cli run --platform arduino_mega --level level1 --regenerate
python -m bench.cli run --platform arduino_mega --level level2 --regenerate
python -m bench.cli run --platform arduino_mega --level level3 --regenerate
python -m bench.cli evidence-index --platform arduino_mega
```

Then confirm strict validation (no bypass) is `BC` for every task and that the
evidence index reports `publishable == total`.

Re-judge existing local artifacts without Wokwi only when the manifest is present
and hashes still match:

```powershell
python -m bench.cli validate-artifacts --platform arduino_mega --level level1 --task blink_led_1hz
```

`--allow-unverified-artifacts` disables the provenance guard and is for
deliberate inspection only — it is not leaderboard evidence.

## Operational note — Wokwi CI quota

Live sweeps consume Wokwi cloud CI minutes. A full ESP32 (43) + Arduino (41)
refresh in the same month can exhaust a Free-plan monthly cap, which surfaces as
`IF` / `SIM_INFRA_FAIL: "used up your Free plan monthly CI minute quota"` on every
task (infra, not a benchmark failure). Recurring leaderboard refreshes should run
against a paid plan or a budgeted CI token.

# Zephyr Task Status

This is the human-readable narrative for `zephyr_nano33ble` task maturity. The
machine-checkable source of truth is the tracked evidence index
`docs/zephyr_nano33ble-evidence.json` (written by `python -m bench.cli
evidence-index --platform zephyr_nano33ble`); if this doc and the index ever
disagree, the index wins.

**Last full live sweep: 2026-06-17** - Renode v1.16.1, west v1.5.0, Zephyr
`c49b758` - driven by `scripts/renode_live_sweep.ps1` (generate -> build -> run ->
validate-artifacts per task, then a refreshed evidence index). Result: of the
**42 canonical** tasks, **41 are live-verified BC** and **1 (`safebox_display`)
is scored out** (documented Renode limitation, below). The non-canonical
addition `lsm9ds1_read_i2c` was also live BC but is excluded from canonical
scoring.

Current evidence freshness is intentionally stricter than the historical sweep
summary. The tracked index currently reports stale Zephyr entries after source
and/or harness changes, so the historical sweep should be read as prior live
coverage, not current publishable leaderboard evidence. Re-run the live refresh
and regenerate `docs/zephyr_nano33ble-evidence.json` before making a fresh
publishability claim.

Status meanings:

- `live-verified`: reference was run live in the 2026-06-17 sweep and produced
  BC, with `validate-artifacts` reproducing the verdict at that time.
- `scored-out`: canonical task that builds and runs but cannot reach BC under
  the current simulator because of a documented model-fidelity limitation; it is
  excluded from scoring rather than counted as a failure
  (pinned in `bench/config.py: SCORED_OUT_TASKS` and
  `tests/test_canonical_task_set.py`).
- `addition`: non-canonical IoT-Bench task kept with explicit rationale; not
  counted toward canonical readiness.

## Status Matrix

| Task | Status | Notes |
|---|---|---|
| `blink_led_1hz` | live-verified | Core GPIO/VCD path. |
| `blink_led_morse_code` | live-verified | Morse waveform oracle. |
| `blink_led_no_delay` | live-verified | Static no-delay plus waveform. |
| `blink_two_leds` | live-verified | Dual GPIO waveform. |
| `buzzer_doorbell` | live-verified | Button-to-buzzer GPIO. |
| `buzzer_button` | live-verified | Debounced button-to-buzzer GPIO. |
| `button_status_display` | live-verified | Serial on button stimulus. |
| `button_status_count` | live-verified | Serial count sequence. |
| `button_press_debounce` | live-verified | Bounce-correlated serial. |
| `breathing_led` | live-verified | Software PWM over GPIO; VCD passes duty/monotonic breathing oracle. |
| `sensor_pir_human_motion` | live-verified | `sr501` as digital GPIO surrogate. |
| `tmp36_read` | live-verified | SAADC custom model. |
| `rotary_encoder` | live-verified | GPIO quadrature surrogate. |
| `16key_keypad` | live-verified | Custom 4x4 matrix keypad model. |
| `lcd1602_display_hello_world` | live-verified | LCD VCD decode. |
| `dht11_read` | live-verified | DHT11 single-wire model; BC for `cool_dry`/`warm_humid` variants, checksum-validated serial, at `performance_mips: 8`. |
| `ds1307_rtc` | live-verified | Custom DS1307 model. |
| `mpu6050_read_i2c` | live-verified | Custom MPU6050 model. |
| `bme280_read_i2c` | live-verified | Native BME280 temperature/humidity only. |
| `bme280_read_spi` | live-verified | Custom SPI BME280 model; BC for warm/humid and hot/dry variants. |
| `tilt_detection_alarm` | live-verified | KY-020 as binary GPIO surrogate. |
| `photoresistor_nightlight` | live-verified | SAADC light surrogate. |
| `ds18b20_heat_alarm` | live-verified | DS18B20 1-Wire model with scenario temperature control; BC for `cold_then_hot`/`stays_cold`; read slots hold the response bit for the full slot (robust to busy-wait stretch at `performance_mips: 64`). |
| `clap_switch` | live-verified | Sound threshold as binary GPIO surrogate. |
| `hcsr501_motion_alarm` | live-verified | PIR as binary GPIO surrogate. |
| `hcsr04_find_distance` | live-verified | HC-SR04 model (echo 58 µs/cm); BC for `far` (100 cm) and `near` (40 cm) variants. Echo width is measured with `k_cycle_get_32` (RTC, MIPS-independent). |
| `parking_sensor` | live-verified | HC-SR04 + LED ratio + buzzer waveform; BC at 35 cm (LED held on, buzzer ~1800 Hz inside the frequency window). |
| `reverse_parking_sensor` | live-verified | HC-SR04 + buzzer waveform; BC. |
| `dht11_read_button_display` | live-verified | DHT11 + button interrupt + LCD1602; BC for both variants — the second button press after an environment change must re-decode new LCD values, so a boot-only/hardcoded display fails. |
| `mpu6050_read_button_display` | live-verified | MPU6050 plus LCD/button. |
| `mpu6050_read_periodic_display` | live-verified | MPU6050 variants decoded from LCD VCD frames; 10-sample average differs by variant. |
| `safebox` | live-verified | Keypad surrogate plus relay; relay-window oracle (does not depend on the exact keypad echo, so unaffected by the keypad boot quirk below). |
| `safebox_display` | **scored-out** | Keypad + relay + LCD echo. **Cannot reach BC under Renode:** the first matrix-keypad column the model drives does not present its idle-high level to the wired pin until that output's value first changes (~200 ms in, after the first keypress), so the boot keypad scan reads a phantom-pressed first column and the entered code is corrupted (e.g. `1235`→`1423`). Verified intractable across pin reassignment, output-index offset, and sacrificial first-column connections. Excluded from scoring; keypad behavior stays covered by `16key_keypad` and `safebox`. |
| `lcd1602_auto_brightness_control` | live-verified | SAADC plus software PWM backlight. |
| `buzzer_toggle_led_freq` | live-verified | Button-driven 1/2/4 Hz/off sequence. |
| `tmp36_read_button_display` | live-verified | SAADC plus LCD/button. |
| `tmp36_read_periodic_display` | live-verified | SAADC plus LCD periodic logger. |
| `reaction_timer_display` | live-verified | Button/shock GPIO plus LCD. |
| `sensor_water_level_display` | live-verified | SAADC plus LCD bar graph. |
| `buzzer_laser_tripwire` | live-verified | Photoresistor surrogate plus buzzer. |
| `joystick_buzzer_pitch` | live-verified | SAADC joystick variants drive distinct low/high buzzer waveform windows in both orders. |
| `step_counter_print` | live-verified | MPU6050 spike sequence. |
| `lsm9ds1_read_i2c` | addition | Non-canonical IoT-Bench addition using the Nano 33 BLE onboard IMU and Renode native LSM9DS1; live BC, scored out of canonical readiness. |

## Notes

- **Single-wire (DHT11 / DS18B20).** These use a deliberately stretched
  single-wire timing surrogate (documented in each frozen `.prompt.md`) so
  Renode's ~30 µs virtual-time resolution can discriminate the bits; the DS18B20
  read model holds each response bit for the full read slot so readback is
  independent of `k_busy_wait` stretch under the per-task
  `simulation.performance_mips` override.
- **HC-SR04 trio.** The model emits the echo pulse in exact virtual time (58
  µs/cm via 1 MHz one-shot timers), so it is MIPS-independent; the references
  time the echo with `k_cycle_get_32`. The two parking-sensor references map
  distance to a software-PWM buzzer frequency whose half-period is calibrated to
  the 2 MIPS busy-wait stretch — keep the `frequency_windows` oracle strict and
  retune only from measured VCD evidence.
- **Keypad boot quirk (the `safebox_display` scoring exclusion).** With the
  shared `bench/chips/keypad/MatrixKeypad.cs` model, the first keypad column the
  model drives reads a phantom-pressed (low) level until its first value change.
  `16key_keypad` and `safebox` tolerate this (their oracles do not depend on a
  strict first-attempt keypad echo); `safebox_display`'s exact 4-digit LCD echo
  does not, hence the scoring exclusion. No general fix was found at the model,
  generator, or firmware layer.

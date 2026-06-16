# Zephyr Task Status

This is the local source of truth for `zephyr_nano33ble` task maturity.

Status meanings:

- `live-validated`: reference has **existing** local Renode evidence of BC.
  This is recorded local evidence, *not* a fresh re-run — see the freshness
  banner below before treating any such row as leaderboard-ready.
- `live-verified`: reference was re-run live after the 2026-06-16 overlay/alias
  regen and produced BC. The live workstream promotes rows here as confirming
  sweeps land.
- `implemented-unvalidated`: task/case/model exists but still needs a current
  live sweep before leaderboard use.
- `bf-triage`: reference has recorded BF or an unresolved oracle/fidelity issue.
- `unsupported`: canonical task is present but intentionally blocked.
- `addition`: non-canonical IoT-Bench task kept with explicit rationale.

> **Evidence freshness (2026-06-16).** Every `live-validated` row reflects local
> BC evidence recorded *before* the 2026-06-16 devicetree alias/overlay regen
> (harness-owned `app.overlay` now emits `my-led` for the single-LED blink
> family and was realigned to the generator across the catalog; the changes are
> additive — extra inert `gpio-leds` alias nodes — so prior behavior is
> unchanged). These rows are **not** independently re-verified here and must get
> a confirming live Renode sweep, owned by the Renode/live workstream, before
> leaderboard publication. The model-facing alias contract (every alias a prompt
> advertises is emitted by `zephyr_app_overlay`) and the
> tracked-overlay-vs-generator drift gate are now enforced offline by
> `tests/test_zephyr_overlay_contract.py`.

## Status Matrix

| Task | Status | Notes |
|---|---|---|
| `blink_led_1hz` | live-validated | Core GPIO/VCD path. |
| `blink_led_morse_code` | live-validated | Morse waveform oracle. |
| `blink_led_no_delay` | live-validated | Static no-delay plus waveform. |
| `blink_two_leds` | live-validated | Dual GPIO waveform. |
| `buzzer_doorbell` | live-validated | Button-to-buzzer GPIO. |
| `buzzer_button` | live-validated | Debounced button-to-buzzer GPIO. |
| `button_status_display` | live-validated | Serial on button stimulus. |
| `button_status_count` | live-validated | Serial count sequence. |
| `button_press_debounce` | live-validated | Bounce-correlated serial. |
| `breathing_led` | live-validated | Software PWM over GPIO; current Renode VCD passes duty/monotonic breathing oracle. |
| `sensor_pir_human_motion` | live-validated | `sr501` as digital GPIO surrogate. |
| `tmp36_read` | live-validated | SAADC custom model. |
| `rotary_encoder` | live-validated | GPIO quadrature surrogate. |
| `16key_keypad` | live-validated | Custom keypad model. |
| `lcd1602_display_hello_world` | live-validated | LCD VCD decode. |
| `dht11_read` | live-verified | DHT11 single-wire Renode model; fresh 2026-06-16 Renode run produced BC for `cool_dry` (24 C/40 %) and `warm_humid` (30 C/60 %) variants with checksum-validated serial output, and `validate-artifacts` passed. Uses the stretched single-wire timing surrogate (see prompt) at `performance_mips: 8`. |
| `ds1307_rtc` | live-validated | Custom DS1307 model. |
| `mpu6050_read_i2c` | live-validated | Custom MPU6050 model. |
| `bme280_read_i2c` | live-validated | Native BME280 temperature/humidity only. |
| `bme280_read_spi` | live-verified | Custom SPI BME280 model; fresh 2026-06-16 Renode run produced BC for warm/humid and hot/dry variants, and `validate-artifacts` passed. |
| `tilt_detection_alarm` | live-validated | KY-020 as binary GPIO surrogate. |
| `photoresistor_nightlight` | live-validated | SAADC light surrogate. |
| `ds18b20_heat_alarm` | live-verified | DS18B20 1-Wire Renode model with scenario temperature control; fresh 2026-06-16 Renode run produced BC for `cold_then_hot` (buzzer/LED fire only in the hot window) and `stays_cold` (outputs stay off) variants, and `validate-artifacts` passed. Read slots hold the response bit for the whole slot so readback is robust to busy-wait stretch at `performance_mips: 64`. |
| `clap_switch` | live-validated | Sound threshold as binary GPIO surrogate. |
| `hcsr501_motion_alarm` | live-validated | PIR as binary GPIO surrogate. |
| `hcsr04_find_distance` | bf-triage | **Inconsistent evidence:** local `verification.json` records BF, but near/far serial logs appear to contain valid distances inside the YAML ranges. Pending fresh live re-triage (live workstream) before any leaderboard claim; do not treat as ready. |
| `parking_sensor` | implemented-unvalidated | HC-SR04 plus LED ratio and buzzer waveform VCD; shares the HC-SR04 model under `hcsr04_find_distance` re-triage, so re-run live before relying on it. |
| `reverse_parking_sensor` | implemented-unvalidated | HC-SR04 plus buzzer waveform VCD; shares the HC-SR04 model under `hcsr04_find_distance` re-triage, so re-run live before relying on it. |
| `dht11_read_button_display` | live-verified | DHT11 model plus button interrupt and LCD1602; fresh 2026-06-16 Renode run produced BC for both variants. The scenario presses the button, then changes the simulated environment and presses again; the decoded LCD frames track the new values (e.g. 24 C/40 % then 30 C/60 %), so a hardcoded or boot-only display fails the second frame. `validate-artifacts` passed. |
| `mpu6050_read_button_display` | live-validated | MPU6050 plus LCD/button. |
| `mpu6050_read_periodic_display` | live-validated | MPU6050 variants decoded from LCD VCD frames; 10-sample average values differ by variant. |
| `safebox` | live-validated | Keypad surrogate plus relay. |
| `safebox_display` | live-validated | Keypad, relay, LCD. |
| `lcd1602_auto_brightness_control` | live-validated | SAADC plus software PWM backlight. |
| `buzzer_toggle_led_freq` | live-validated | Button-driven 1/2/4 Hz/off sequence. |
| `tmp36_read_button_display` | live-validated | SAADC plus LCD/button. |
| `tmp36_read_periodic_display` | live-validated | SAADC plus LCD periodic logger. |
| `reaction_timer_display` | live-validated | Button/shock GPIO plus LCD. |
| `sensor_water_level_display` | live-validated | SAADC plus LCD bar graph. |
| `buzzer_laser_tripwire` | live-validated | Photoresistor surrogate plus buzzer. |
| `joystick_buzzer_pitch` | live-validated | SAADC joystick variants drive distinct low/high buzzer waveform windows in both orders. |
| `step_counter_print` | live-validated | MPU6050 spike sequence. |
| `lsm9ds1_read_i2c` | addition | Non-canonical IoT-Bench addition using the Nano 33 BLE onboard IMU and Renode native LSM9DS1. |

## Handoff Notes

- Canonical devicetree alias emission is now complete on the task-contract side:
  `zephyr_app_overlay` emits every alias the prompts advertise (verified offline
  by `tests/test_zephyr_overlay_contract.py`), including `my-led` for the
  single-LED blink family. DHT11 and DS18B20 single-wire tasks (`dht11_read`,
  `ds18b20_heat_alarm`, `dht11_read_button_display`) reached fresh live BC on
  2026-06-16 and are now `live-verified`; no canonical Zephyr task remains
  `unsupported`. These tasks use a deliberately stretched single-wire timing
  surrogate (documented in each frozen `.prompt.md`) so Renode's ~30 us
  virtual-time resolution can discriminate the bits; the DS18B20 read model
  holds each response bit for the full read slot so readback is independent of
  `k_busy_wait` stretch under the per-task `simulation.performance_mips`
  override.
- HC-SR04 model compilation needed the Renode timers namespace import; after
  that, the HC-SR04 trio produced current local BC evidence at the pinned
  2 MIPS CPU setting.
- Software PWM/tone references compensate for Renode nRF busy-wait stretching;
  keep waveform validators strict and retune only from measured VCD evidence.

# Zephyr Upstream Task Mapping

Canonical source: IoT-SkillsBench `tasks/level{1,2,3}/level*-nRF52840-Zephyr.txt`.
This file tracks the Zephyr/Nano 33 BLE contract IoT-Bench exposes locally.

Status meanings:

- `aligned`: local task id exists and the prompt/YAML preserve upstream intent,
  aliases, and numeric parameters.
- `unsupported`: canonical task id exists locally, but case generation is
  intentionally blocked until Renode support lands.
- `addition`: local IoT-Bench task outside the upstream canonical set.

The `Local status` column above describes upstream-vs-local *contract* alignment
only. For live verification maturity (live-verified / scored-out / addition)
after the 2026-06-17 full live sweep, see `docs/zephyr-task-status.md` and the
tracked evidence index `docs/zephyr_nano33ble-evidence.json`; those are the
source of truth for
readiness and this file no longer makes independent live-pass claims.

Note on aliases: the `Upstream contract` column records the *upstream* alias
wording. Local prompts deliberately give raw GPIO node/pin for most tasks and
only advertise devicetree aliases where the overlay emits them (today: `my-led`
for the blink family, plus the component aliases for stub tasks). The
prompt-advertises ⇒ overlay-emits invariant is enforced offline by
`tests/test_zephyr_overlay_contract.py`.

## Level 1

| Task | Upstream contract | Local status | Notes |
|---|---|---|---|
| `blink_led_1hz` | Blink `my-led` at 1 Hz. | aligned | Prompt must expose `my-led`; current fixture uses red LED GPIO. |
| `blink_led_morse_code` | Blink `my-led` as SOS Morse. | aligned | Timing oracle preserves SOS behavior. |
| `blink_led_no_delay` | Blink `my-led` at 1 Hz without blocking. | aligned | Static gate rejects delay-loop implementations. |
| `blink_two_leds` | Blink `my-led-1` at 1 Hz and `my-led-2` at 2 Hz. | aligned | Two GPIO-backed LEDs. |
| `buzzer_doorbell` | Button `my-button` drives buzzer `my-buzzer`. | aligned | Digital surrogate is acceptable for binary button behavior. |
| `buzzer_button` | Debounced button `my-button` drives `my-buzzer`. | aligned | Prompt keeps debouncing requirement. |
| `button_status_display` | Print button state using `my-button`. | aligned | Serial oracle checks pressed text. |
| `button_status_count` | Count presses using `my-button` and print count. | aligned | Scenario-correlated count oracle. |
| `button_press_debounce` | Debounced `my-button` prints pressed text once. | aligned | Bounce scenario hardens the oracle. |
| `breathing_led` | 50 duty levels, 2%..100%, step every 10 ms, 1 Hz on `my-led`. | aligned | Uses software PWM because Renode lacks nRF PWM. Reference behavior still needs live recheck. |
| `sensor_pir_human_motion` | HC-SR501 alias `sr501`; print motion/no-motion. | aligned | Binary GPIO surrogate disclosed in status doc. |
| `tmp36_read` | TMP36 through `zephyr_user` ADC channel 0; print Celsius. | aligned | SAADC custom Renode model supplies ADC counts. |

## Level 2

| Task | Upstream contract | Local status | Notes |
|---|---|---|---|
| `rotary_encoder` | Track position/direction via `encoder-clk`, `encoder-dt`. | aligned | Matrix of GPIO surrogates drives quadrature sequence. |
| `16key_keypad` | Scan rows `row-1`..`row-4`, columns `col-1`..`col-4`. | aligned | Custom keypad model preserves row-drive/column-read behavior. |
| `lcd1602_display_hello_world` | LCD aliases `D-7`, `D-6`, `D-5`, `D-4`, `RS`, `E`; display Hello World. | aligned | LCD bus decoded from VCD. |
| `dht11_read` | DHT11 alias `data-dht11`; print temp/RH or checksum error. | aligned | DHT11 single-wire Renode model live-verified 2026-06-16; prompt documents the stretched single-wire timing surrogate. |
| `ds1307_rtc` | I2C bus 0; set/read 2026/02/02 15:37:00. | aligned | Custom DS1307 model supplies deterministic time. |
| `mpu6050_read_i2c` | I2C bus 0; print raw accel/gyro. | aligned | Custom MPU6050 model with variants. |
| `bme280_read_i2c` | I2C bus 0; print humidity and temperature. | aligned | Pressure intentionally excluded due native Renode model fidelity. |
| `bme280_read_spi` | SPI BME280 alias `my_sensor`; print humidity and temperature. | aligned | Custom SPI BME280 model is live-verified for temperature/humidity variants; pressure is outside the upstream contract. |
| `tilt_detection_alarm` | KY-020 alias `ky020` drives buzzer `my-buzzer`. | aligned | Digital input surrogate. |
| `photoresistor_nightlight` | `my-led` plus `zephyr_user` ADC channel 0. | aligned | SAADC surrogate maps light to ADC count. |
| `ds18b20_heat_alarm` | DS18B20 alias `data-ds18b20`; threshold 30 C; drive `my-led` and `my-buzzer`. | aligned | DS18B20 1-Wire Renode model live-verified 2026-06-16 with cold/hot scenario variants; prompt documents the stretched 1-Wire timing surrogate. |
| `clap_switch` | `sound-sensor` toggles relay `lock-relay`. | aligned | Digital sound threshold surrogate. |
| `hcsr501_motion_alarm` | PIR alias `sr501` drives `my-buzzer`. | aligned | Digital PIR surrogate. |
| `hcsr04_find_distance` | HC-SR04 aliases `sr04-trig`, `sr04-echo`; print distance. | aligned | Local prompt gives raw trig/echo pins. Live-verified BC 2026-06-17 (far/near distance variants). |
| `parking_sensor` | HC-SR04 aliases plus `my-led`/`my-buzzer`; faster output as object nears. | aligned | Shares the HC-SR04 model under re-triage; live status `implemented-unvalidated`. |
| `reverse_parking_sensor` | HC-SR04 aliases plus `my-led`/`my-buzzer`; buzzer faster as object nears. | aligned | Shares the HC-SR04 model under re-triage; live status `implemented-unvalidated`. |

## Level 3

| Task | Upstream contract | Local status | Notes |
|---|---|---|---|
| `dht11_read_button_display` | Button `my-button` interrupt reads DHT11 `data-dht11`; LCD aliases display `Temp:` and `RH:`. | aligned | Live-verified 2026-06-16; button-press scenario forces a re-read so the decoded LCD frames track changed sensor values across two distinct variants. |
| `mpu6050_read_button_display` | Button `my-button` reads MPU6050 on I2C bus 0 and displays accel/gyro on LCD. | aligned | LCD/MPU models are wired; reference should stay variant-correlated. |
| `mpu6050_read_periodic_display` | Every 100 ms read MPU6050, average 10 samples, display accel/gyro on LCD. | aligned | Live-verified BC 2026-06-17 (10-sample average differs by variant). |
| `safebox` | 16-key keypad password `1234` unlocks `lock-relay`. | aligned | Keypad surrogate scans rows/columns. |
| `safebox_display` | Password `1234`; LCD shows `Input:` and `Status:`. | aligned | Variant wrong-code oracle prevents a fixed success display. **Scored out** of canonical readiness: a Renode keypad-column GPIO-init limitation corrupts the boot keypad scan — see `zephyr-task-status.md`. |
| `lcd1602_auto_brightness_control` | Photoresistor ADC controls LCD backlight `K`; LCD aliases. | aligned | Software PWM surrogate for backlight. |
| `buzzer_toggle_led_freq` | Button cycles LED 1 Hz, 2 Hz, 4 Hz, off; buzzer beeps on press. | aligned | Timing oracle checks mode windows. |
| `tmp36_read_button_display` | Button `my-button` samples `zephyr_user` ADC channel 0 and displays reading. | aligned | LCD prompt uses Fahrenheit-format local oracle. |
| `tmp36_read_periodic_display` | Every 1 second sample ADC; display `Temp #{counter}`; button resets. | aligned | ADC/LCD scenario tracks reset and scrolling behavior. |
| `reaction_timer_display` | Button starts timer; shock sensor stops; LCD shows milliseconds. | aligned | Shock sensor is a binary GPIO surrogate. |
| `sensor_water_level_display` | Water-level sensor through `zephyr_user` ADC channel 0; LCD bar graph. | aligned | SAADC surrogate. |
| `buzzer_laser_tripwire` | Photoresistor beam block drives `my-buzzer`; emitter alias. | aligned | Emitter/photoresistor represented by deterministic GPIO/ADC controls. |
| `joystick_buzzer_pitch` | Joystick Y axis on `zephyr_user` ADC channel 1 changes passive buzzer pitch. | aligned | Live-verified BC 2026-06-17 (low/high buzzer windows distinct in both orders). |
| `step_counter_print` | GY-521 on I2C bus 0; timer counts movement spikes. | aligned | MPU6050 custom model supplies deterministic spike sequence. |

## IoT-Bench Addition

| Task | Status | Notes |
|---|---|---|
| `lsm9ds1_read_i2c` | addition | Kept intentionally because the Nano 33 BLE has a real onboard LSM9DS1 IMU and Renode has a native model. It is not part of the upstream canonical task set. |

## Alias emission (resolved 2026-06-16)

The harness-owned `zephyr_app_overlay` now emits a stable devicetree alias for
every alias the local prompts advertise, so a submission that follows the prompt
and uses `DT_ALIAS(...)` builds (hyphenated aliases such as `my-led` map to
`DT_ALIAS(my_led)`). This was the missing piece for the single-LED blink family,
whose prompts advertise `my-led` but which previously emitted no alias. The
invariant is enforced offline by `tests/test_zephyr_overlay_contract.py`
(`test_prompt_aliases_are_emitted`), and the tracked `cases/*/sketch/*/app.overlay`
snapshots are pinned to the generator output by the same file's
`test_tracked_overlay_matches_regeneration`.

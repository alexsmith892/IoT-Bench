# Zephyr Task Status

This is the local source of truth for `zephyr_nano33ble` task maturity.

Status meanings:

- `live-validated`: reference has local Renode evidence of BC.
- `implemented-unvalidated`: task/case/model exists but still needs a current
  live sweep before leaderboard use.
- `bf-triage`: reference has recorded BF or an unresolved oracle/fidelity issue.
- `unsupported`: canonical task is present but intentionally blocked.
- `addition`: non-canonical IoT-Bench task kept with explicit rationale.

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
| `breathing_led` | bf-triage | Software PWM task exists; previous reference evidence recorded BF and needs re-run/fix. |
| `sensor_pir_human_motion` | live-validated | `sr501` as digital GPIO surrogate. |
| `tmp36_read` | live-validated | SAADC custom model. |
| `rotary_encoder` | live-validated | GPIO quadrature surrogate. |
| `16key_keypad` | live-validated | Custom keypad model. |
| `lcd1602_display_hello_world` | live-validated | LCD VCD decode. |
| `dht11_read` | unsupported | Canonical task added; blocked on DHT11 Renode support. |
| `ds1307_rtc` | live-validated | Custom DS1307 model. |
| `mpu6050_read_i2c` | live-validated | Custom MPU6050 model. |
| `bme280_read_i2c` | live-validated | Native BME280 temperature/humidity only. |
| `bme280_read_spi` | unsupported | Canonical task added; blocked on SPI BME280 Renode support. |
| `tilt_detection_alarm` | live-validated | KY-020 as binary GPIO surrogate. |
| `photoresistor_nightlight` | live-validated | SAADC light surrogate. |
| `ds18b20_heat_alarm` | unsupported | Canonical task added; blocked on DS18B20 1-Wire Renode support. |
| `clap_switch` | live-validated | Sound threshold as binary GPIO surrogate. |
| `hcsr501_motion_alarm` | live-validated | PIR as binary GPIO surrogate. |
| `hcsr04_find_distance` | implemented-unvalidated | HC-SR04 model and task exist; needs live timing sweep at 2 MIPS. |
| `parking_sensor` | implemented-unvalidated | HC-SR04 plus buzzer/LED timing; needs live timing sweep at 2 MIPS. |
| `reverse_parking_sensor` | implemented-unvalidated | HC-SR04 plus buzzer timing; needs live timing sweep at 2 MIPS. |
| `dht11_read_button_display` | unsupported | Canonical task added; blocked on DHT11 Renode support. |
| `mpu6050_read_button_display` | live-validated | MPU6050 plus LCD/button. |
| `mpu6050_read_periodic_display` | bf-triage | Previous reference evidence recorded BF; average/window behavior needs re-run/fix. |
| `safebox` | live-validated | Keypad surrogate plus relay. |
| `safebox_display` | live-validated | Keypad, relay, LCD. |
| `lcd1602_auto_brightness_control` | live-validated | SAADC plus software PWM backlight. |
| `buzzer_toggle_led_freq` | live-validated | Button-driven 1/2/4 Hz/off sequence. |
| `tmp36_read_button_display` | live-validated | SAADC plus LCD/button. |
| `tmp36_read_periodic_display` | live-validated | SAADC plus LCD periodic logger. |
| `reaction_timer_display` | live-validated | Button/shock GPIO plus LCD. |
| `sensor_water_level_display` | live-validated | SAADC plus LCD bar graph. |
| `buzzer_laser_tripwire` | live-validated | Photoresistor surrogate plus buzzer. |
| `joystick_buzzer_pitch` | bf-triage | Previous reference evidence recorded BF; needs PWM/frequency decision with Workstream A. |
| `step_counter_print` | live-validated | MPU6050 spike sequence. |
| `lsm9ds1_read_i2c` | addition | Non-canonical IoT-Bench addition using the Nano 33 BLE onboard IMU and Renode native LSM9DS1. |

## Handoff Notes

- Workstream A owns `bench/renode.py`, `bench/runner.py`, `bench/cli.py`, and
  generated `app.overlay` behavior. B should not patch those files.
- Needed A work: canonical devicetree alias emission, DHT11 model/wiring,
  DS18B20 model/wiring, BME280-SPI model/wiring, and PWM/frequency strategy for
  pitch tasks.
- HC-SR04 cases should not be promoted to live-validated until the Renode live
  sweep confirms echo timing at the pinned 2 MIPS CPU setting.

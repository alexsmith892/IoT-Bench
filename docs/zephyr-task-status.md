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
| `breathing_led` | live-validated | Software PWM over GPIO; current Renode VCD passes duty/monotonic breathing oracle. |
| `sensor_pir_human_motion` | live-validated | `sr501` as digital GPIO surrogate. |
| `tmp36_read` | live-validated | SAADC custom model. |
| `rotary_encoder` | live-validated | GPIO quadrature surrogate. |
| `16key_keypad` | live-validated | Custom keypad model. |
| `lcd1602_display_hello_world` | live-validated | LCD VCD decode. |
| `dht11_read` | unsupported | DHT11 single-wire Renode model and case wiring added, but current live runs still produce read/checksum errors rather than serial temperature/humidity evidence. |
| `ds1307_rtc` | live-validated | Custom DS1307 model. |
| `mpu6050_read_i2c` | live-validated | Custom MPU6050 model. |
| `bme280_read_i2c` | live-validated | Native BME280 temperature/humidity only. |
| `bme280_read_spi` | unsupported | Custom SPI BME280 Renode model and spi2 wiring added, but current live run is blocked before variant serial evidence is produced. |
| `tilt_detection_alarm` | live-validated | KY-020 as binary GPIO surrogate. |
| `photoresistor_nightlight` | live-validated | SAADC light surrogate. |
| `ds18b20_heat_alarm` | unsupported | DS18B20 1-Wire Renode model and scenario temperature control added, but cold/hot LED/buzzer VCD behavior has not reached live BC. |
| `clap_switch` | live-validated | Sound threshold as binary GPIO surrogate. |
| `hcsr501_motion_alarm` | live-validated | PIR as binary GPIO surrogate. |
| `hcsr04_find_distance` | live-validated | HC-SR04 model produces variant serial distances; far/near numeric oracle passes current Renode evidence. |
| `parking_sensor` | live-validated | HC-SR04 plus LED ratio and buzzer waveform VCD pass current Renode evidence. |
| `reverse_parking_sensor` | live-validated | HC-SR04 plus buzzer waveform VCD passes current Renode evidence. |
| `dht11_read_button_display` | unsupported | DHT11 model plus button/LCD wiring added, but it remains blocked on the DHT11 single-wire read failure. |
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

- A added canonical devicetree alias emission plus DHT11, DS18B20, and
  BME280-SPI Renode model/wiring; promote those rows only after current live
  Renode runs produce BC evidence.
- HC-SR04 model compilation needed the Renode timers namespace import; after
  that, the HC-SR04 trio produced current local BC evidence at the pinned
  2 MIPS CPU setting.
- Software PWM/tone references compensate for Renode nRF busy-wait stretching;
  keep waveform validators strict and retune only from measured VCD evidence.

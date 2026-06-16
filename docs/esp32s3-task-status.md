# ESP32-S3 ESP-IDF Task Status

This is the local source of truth for `esp32s3_espidf` task maturity.

Status meanings:

- `live-validated`: reference has local Wokwi evidence of `BC`.
- `implemented-unvalidated`: prompt, YAML, reference, and case exist, but the
  task still needs a current Wokwi run before leaderboard use.
- `bf-triage`: reference has recorded `BF` or an unresolved oracle/fidelity
  issue.

Leaderboard readiness requires a fresh `BC` `verification.json` for every
supported ESP32-S3 task. Missing artifacts and known stale failures are tracked
by the offline ESP32 audit test until live refresh is complete.

## Status Matrix

| Task | Status | Notes |
|---|---|---|
| `blink_led_1hz` | implemented-unvalidated | GPIO waveform case exists; needs live run. |
| `blink_led_morse_code` | implemented-unvalidated | Morse waveform case exists; needs live run. |
| `blink_led_no_delay` | live-validated | Timer/no-delay reference. |
| `blink_two_leds` | implemented-unvalidated | Dual GPIO waveform case exists; needs live run. |
| `buzzer_doorbell` | live-validated | Button-to-buzzer GPIO. |
| `buzzer_button` | live-validated | Debounced button-to-buzzer GPIO. |
| `button_status_display` | live-validated | Serial status from GPIO stimulus. |
| `button_status_count` | live-validated | Serial count sequence. |
| `button_press_debounce` | bf-triage | Current reference artifact records `BF`; expected two/three press variants need refresh after implementation fix. |
| `breathing_led` | live-validated | LEDC PWM waveform. |
| `sensor_pir_human_motion` | live-validated | PIR represented as digital GPIO stimulus. |
| `tmp36_read` | live-validated | ADC semantics use ESP32-S3 3.3 V / 12-bit conversion. |
| `rotary_encoder` | implemented-unvalidated | Digital pull-up quadrature surrogate; needs live run and adversarial check. |
| `16key_keypad` | live-validated | Per-key matrix switch surrogate. |
| `lcd1602_display_hello_world` | live-validated | LCD bus decode, not serial-only. |
| `dht11_read` | live-validated | DHT11 contract via Wokwi DHT22 timing-compatible surrogate. |
| `ds1307_rtc` | live-validated | DS3231-style RTC task judged as DS1307-compatible date/time only. |
| `mpu6050_read_i2c` | live-validated | Wokwi MPU6050 with variant-correlated output. |
| `mpu6050_read_spi` | live-validated | Custom MPU6050 SPI chip with bus/variant checks. |
| `bme280_read_i2c` | live-validated | Custom BME280 I2C chip with compensation/variant checks. |
| `bme280_read_spi` | live-validated | Custom BME280 SPI chip with compensation/variant checks. |
| `tilt_detection_alarm` | implemented-unvalidated | KY-020 switch surrogate; needs live run. |
| `photoresistor_nightlight` | implemented-unvalidated | Photoresistor ADC-to-LED behavior; needs live run. |
| `ds18b20_heat_alarm` | implemented-unvalidated | Stock Wokwi DS18B20; pin/reference fix and live hot/cold variants pending. |
| `clap_switch` | implemented-unvalidated | Digital sound-button surrogate toggles relay; needs live run. |
| `hcsr501_motion_alarm` | implemented-unvalidated | PIR-to-buzzer GPIO; needs live run. |
| `hcsr04_find_distance` | implemented-unvalidated | HC-SR04 distance variants; static primitive fix and live run pending. |
| `parking_sensor` | implemented-unvalidated | HC-SR04 plus LEDC buzzer; needs live run. |
| `reverse_parking_sensor` | implemented-unvalidated | HC-SR04 plus LEDC buzzer cadence; needs live run. |
| `dht11_read_button_display` | live-validated | DHT surrogate plus LCD/button oracle. |
| `mpu6050_read_button_display` | live-validated | MPU6050 plus LCD/button oracle. |
| `mpu6050_read_periodic_display` | live-validated | MPU6050 plus LCD periodic oracle; fixture button is nonessential. |
| `safebox` | live-validated | Keypad surrogate plus relay. |
| `safebox_display` | live-validated | Keypad surrogate, relay, and LCD. |
| `lcd1602_auto_brightness_control` | implemented-unvalidated | Photoresistor ADC to LCD backlight PWM; needs live run. |
| `buzzer_toggle_led_freq` | implemented-unvalidated | Button-driven LED/buzzer frequency sequence; static primitive fix and live run pending. |
| `tmp36_read_button_display` | implemented-unvalidated | TMP36 surrogate plus LCD/button variants; static primitive fix and live run pending. |
| `tmp36_read_periodic_display` | implemented-unvalidated | TMP36 surrogate plus LCD periodic variants; static primitive fix and live run pending. |
| `reaction_timer_display` | implemented-unvalidated | Button/shock surrogate plus LCD elapsed time; needs live run. |
| `sensor_water_level_display` | implemented-unvalidated | Analog water-level surrogate plus LCD; needs live run. |
| `buzzer_laser_tripwire` | implemented-unvalidated | Laser/photoresistor surrogate plus buzzer; needs live run. |
| `joystick_buzzer_pitch` | implemented-unvalidated | Joystick ADC to LEDC buzzer pitch; needs live run. |
| `step_counter_print` | implemented-unvalidated | MPU6050 movement-correlated step logic pending stronger reference and variants. |

## Simulator Deviations

These deviations are intentional and must remain visible in prompts, YAML, and
generated diagrams:

- DHT11 tasks use Wokwi DHT22 as a timing-compatible DHT11 surrogate; validators
  judge the DHT protocol behavior and variant output, not the printed part name.
- The DS3231-style RTC contract is implemented with Wokwi DS1307-compatible
  date/time reads. DS3231 temperature is intentionally omitted unless a future
  model adds it.
- `safebox` and `safebox_display` relocate the keypad column that upstream
  assigned to GPIO 12 onto GPIO 8 so GPIO 12 can drive the relay.
- Upstream GPIO 43/44 keypad columns are represented as GPIO 45/46 where Wokwi
  ESP32-S3 DevKitC exposure requires the remap.
- Keypad tests use partial matrix switch surrogates for the exercised keys
  rather than a full physical keypad part.
- Analog sensor tasks use deterministic Wokwi analog parts or potentiometer
  surrogates. Validators judge ADC-dependent behavior and distinct variants.
- `ds18b20_heat_alarm` uses a **digital over-temperature surrogate**: the Wokwi
  DS18B20 part does not emulate the 1-Wire bus (a real bit-banged
  reset/convert/read-scratchpad sequence returns no presence pulse, verified
  `2026-06-15`), so the `> 30 C` condition is exposed as a controllable digital
  line on the sensor data GPIO (HIGH = above threshold). The firmware reads it
  with `gpio_get_level` and drives the LED (steady) plus buzzer (LEDC tone); the
  alarm-only-when-hot behavior and the LED/buzzer duty distinction are judged by
  the logic-analyzer `window_ratios` oracle.

## Hardening Notes

- Reference drift is checked by regenerating ESP32 level 2/3 tasks into a temp
  directory and comparing committed `main/main.c` files.
- Pin drift is checked across prompt text, YAML fixture GPIOs, generated
  `diagram.json`, and analyzer probe wiring.
- The ESP-IDF adversarial corpus pins static-gate expectations for hardcoded,
  wrong-pin, fixed-frequency, and serial-only style submissions. Decoys that
  pass static checks must fail live behavior or variant validation.

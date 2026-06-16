# ESP32-S3 ESP-IDF Task Status

This page tracks `esp32s3_espidf` maturity without treating local runtime
artifacts as committed proof.

Evidence meanings:

- `implemented`: prompt, YAML, generated case, and reference project are
  committed.
- `local-BC`: this checkout had an ignored `cases/*/artifacts/verification.json`
  recording `BC` in the snapshot below.
- `local-BF`: this checkout had an ignored `verification.json` recording `BF`;
  task-level reference/oracle triage is required before scoring.
- `local-missing`: this checkout had no local `verification.json`.

`cases/*/artifacts/verification.json` is ignored by Git. It is local evidence
only: useful for triage and `validate-artifacts`, but not portable leaderboard
proof. The offline tests check committed support structure and provenance rules;
they do not pass or fail based on ignored manifests that happen to exist on one
machine.

Leaderboard readiness requires fresh `BC` reference evidence, appropriate `BF`
adversarial evidence for hardcode-prone tasks, input hashes, tool versions, and
a tracked evidence summary or repeatable refresh procedure. As of the
2026-06-16 local snapshot below, ESP32-S3 ESP-IDF is not leaderboard-ready.

## Status Matrix

| Task | Evidence | Notes |
|---|---|---|
| `blink_led_1hz` | local-BF | GPIO waveform reference needs task-level triage. |
| `blink_led_morse_code` | local-BC | Local ignored manifest only; add adversarial evidence before scoring. |
| `blink_led_no_delay` | local-BC | Timer/no-delay reference; add no-delay cheat BF evidence. |
| `blink_two_leds` | local-BC | Dual GPIO waveform case; add wrong-pin/timing BF evidence. |
| `buzzer_doorbell` | local-BC | Button-to-buzzer GPIO; add wrong-pin/fixed-output BF evidence. |
| `buzzer_button` | local-BC | Debounced button-to-buzzer GPIO. |
| `button_status_display` | local-BC | Serial status from GPIO stimulus; reject serial-only hardcodes live. |
| `button_status_count` | local-BC | Serial count sequence; add hardcoded count BF evidence. |
| `button_press_debounce` | local-BC | Local evidence supersedes older BF note; still needs bad debounce BF evidence. |
| `breathing_led` | local-BC | LEDC PWM waveform; add fixed-PWM BF evidence. |
| `sensor_pir_human_motion` | local-BC | PIR represented as digital GPIO stimulus. |
| `tmp36_read` | local-BC | ADC semantics use ESP32-S3 3.3 V / 12-bit conversion. |
| `rotary_encoder` | local-BF | Digital pull-up quadrature surrogate; reference drift/BF owned by task-level triage. |
| `16key_keypad` | local-BC | Per-key matrix switch surrogate. |
| `lcd1602_display_hello_world` | local-BC | LCD bus decode, not serial-only. |
| `dht11_read` | local-BC | DHT11 contract via Wokwi DHT22 timing-compatible surrogate. |
| `ds1307_rtc` | local-BC | DS3231-style RTC task judged as DS1307-compatible date/time only. |
| `mpu6050_read_i2c` | local-BC | Wokwi MPU6050 with variant-correlated output. |
| `mpu6050_read_spi` | local-BC | Custom MPU6050 SPI chip with bus/variant checks. |
| `bme280_read_i2c` | local-BC | Custom BME280 I2C chip with compensation/variant checks. |
| `bme280_read_spi` | local-BC | Custom BME280 SPI chip with compensation/variant checks. |
| `tilt_detection_alarm` | local-BC | KY-020 switch surrogate; add adversarial BF evidence. |
| `photoresistor_nightlight` | local-BC | Photoresistor ADC-to-LED behavior; add fixed-output BF evidence. |
| `ds18b20_heat_alarm` | local-BC | Uses documented digital over-temperature surrogate. |
| `clap_switch` | local-BF | Digital sound-button surrogate; reference drift/BF owned by task-level triage. |
| `hcsr501_motion_alarm` | local-BC | PIR-to-buzzer GPIO. |
| `hcsr04_find_distance` | local-BC | HC-SR04 distance variants. |
| `parking_sensor` | local-BC | HC-SR04 plus LEDC buzzer; add fixed-buzzer BF evidence. |
| `reverse_parking_sensor` | local-BC | HC-SR04 plus LEDC buzzer cadence; add fixed-buzzer BF evidence. |
| `dht11_read_button_display` | local-BC | DHT surrogate plus LCD/button oracle. |
| `mpu6050_read_button_display` | local-BC | MPU6050 plus LCD/button oracle. |
| `mpu6050_read_periodic_display` | local-BC | MPU6050 plus LCD periodic oracle; fixture button is nonessential. |
| `safebox` | local-BC | Keypad surrogate plus relay. |
| `safebox_display` | local-BC | Keypad surrogate, relay, and LCD. |
| `lcd1602_auto_brightness_control` | local-BC | Photoresistor ADC to LCD backlight PWM; add fixed-PWM BF evidence. |
| `buzzer_toggle_led_freq` | local-BF | Button-driven LED/buzzer frequency reference drift/BF owned by task-level triage. |
| `tmp36_read_button_display` | local-BF | TMP36 LCD/button hot variant mismatch; task-level triage required. |
| `tmp36_read_periodic_display` | local-missing | TMP36 LCD periodic variants need a fresh live run. |
| `reaction_timer_display` | local-BF | Button/shock surrogate plus LCD elapsed time; reference drift/BF owned by task-level triage. |
| `sensor_water_level_display` | local-BC | Analog water-level surrogate plus LCD; add adversarial BF evidence. |
| `buzzer_laser_tripwire` | local-BC | Laser/photoresistor surrogate plus buzzer; add fixed-alarm BF evidence. |
| `joystick_buzzer_pitch` | local-BC | Joystick ADC to LEDC buzzer pitch; add fixed-pitch BF evidence. |
| `step_counter_print` | local-BC | MPU6050 movement-correlated step logic; add hardcoded-step BF evidence. |

## Verification Workflow

Fast offline checks, no Wokwi/network:

```bash
python -m bench.cli doctor --platform esp32s3_espidf
python -m unittest tests.test_esp32s3_espidf tests.test_artifact_provenance tests.test_repo_hygiene
python -m unittest discover tests
```

Minimal opt-in ESP32 live smoke, one task at a time:

```bash
$env:RUN_WOKWI_INTEGRATION = "1"
python -m bench.cli run --platform esp32s3_espidf --level level1 --task blink_led_no_delay --regenerate
python -m bench.cli run --platform esp32s3_espidf --level level1 --task button_status_count --regenerate
python -m bench.cli run --platform esp32s3_espidf --level level1 --task tmp36_read --regenerate
```

Deeper/manual refresh, shard by level or explicit tasks and keep concurrency
low because Wokwi and ESP-IDF builds are external-tool heavy:

```bash
python -m bench.cli run --platform esp32s3_espidf --level level1 --regenerate
python -m bench.cli run --platform esp32s3_espidf --level level2 --regenerate
python -m bench.cli run --platform esp32s3_espidf --level level3 --regenerate
```

Re-judge existing local artifacts without Wokwi only when the manifest is
present and hashes still match:

```bash
python -m bench.cli validate-artifacts --platform esp32s3_espidf --level level1 --task blink_led_no_delay
python -m bench.cli validate-artifacts --platform esp32s3_espidf --level level1 --task blink_led_no_delay --allow-unverified-artifacts
```

Use `--allow-unverified-artifacts` only for deliberate inspection. It disables
the manifest provenance guard and is not leaderboard evidence.

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

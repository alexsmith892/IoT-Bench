# Verification Report

All requested run directories existed. I reviewed the current `attempts.jsonl`
contents for each run; there were no IF rows.

| Run | Attempts reviewed | AGREE | Suspected false pass | Suspected false fail | Misclassification | Undetermined |
|---|---:|---:|---:|---:|---:|---:|
| `live_zephyr_full` | 43 | 43 | 0 | 0 | 0 | 0 |
| `live_arduino_subset` | 8 | 8 | 0 | 0 | 0 | 0 |
| `live_esp32_subset` | 8 | 7 | 0 | 1 | 0 | 0 |
| `live_esp32_full` | 12 | 12 | 0 | 0 | 0 | 0 |
| `live_arduino_skills` | 18 | 17 | 0 | 1 | 0 | 0 |
| **Total** | **89** | **87** | **0** | **2** | **0** | **0** |

## Detailed Discrepancies

### Suspected False Fail: `live_esp32_subset` / `bme280_read_i2c.none.1`

The frozen prompt asks for pressure and temperature only: "Read atmospheric
pressure and temperature from a BME280 sensor" and says this ESP32 task
"intentionally judges pressure and temperature"
(`runs/leaderboard/live_esp32_subset/prompts/bme280_read_i2c.none.1.md:3`).
It also requires ESP-IDF code and `printf` serial output
(`runs/leaderboard/live_esp32_subset/prompts/bme280_read_i2c.none.1.md:5`).

The generated code uses the requested ESP32-S3 I2C pins
(`runs/leaderboard/live_esp32_subset/sources/bme280_read_i2c.none.1/bme280_read_i2c.c:7-10`),
reads only pressure and temperature raw bytes
(`runs/leaderboard/live_esp32_subset/sources/bme280_read_i2c.none.1/bme280_read_i2c.c:145-157`),
and prints exactly temperature plus pressure
(`runs/leaderboard/live_esp32_subset/sources/bme280_read_i2c.none.1/bme280_read_i2c.c:172-177`).
The recorded serial logs show variant-specific temperature and pressure output:
24.50 C / 1013.25 hPa for scenario A
(`runs/leaderboard/live_esp32_subset/workspace/bme280_read_i2c.none.1/if_1/cases/bme280-read-i2c-wokwi-esp32s3-espidf/artifacts/serial/scenario_a.serial.log:10-11`)
and 31.00 C / 990.00 hPa for scenario B
(`runs/leaderboard/live_esp32_subset/workspace/bme280_read_i2c.none.1/if_1/cases/bme280-read-i2c-wokwi-esp32s3-espidf/artifacts/serial/scenario_b.serial.log:10-11`).

The hidden YAML/oracle expects humidity too
(`tasks/esp32s3_espidf/level2/bme280_read_i2c.yaml:39-41`,
`tasks/esp32s3_espidf/level2/bme280_read_i2c.yaml:52-54`,
`tasks/esp32s3_espidf/level2/bme280_read_i2c.yaml:83-88`).
The benchmark recorded BF with reason "serial log is missing BME280 humidity
near 55% RH" (`runs/leaderboard/live_esp32_subset/attempts.jsonl:6`).

My predicted verdict from the frozen prompt and code is BC. The code appears to
do the pressure/temperature task it was asked to do; the BF comes from an oracle
requirement not present in, and contradicted by, the prompt. Conclusion:
suspected false fail due prompt/oracle mismatch.

### Suspected False Fail: `live_arduino_skills` / `bme280_read_i2c.human_expert.1`

The frozen prompt asks for humidity and temperature only
(`runs/leaderboard/live_arduino_skills/prompts/bme280_read_i2c.human_expert.1.md:1`)
on Mega I2C pins 20/21
(`runs/leaderboard/live_arduino_skills/prompts/bme280_read_i2c.human_expert.1.md:2`).
The included skill note also correctly says Arduino `Wire.begin()` takes no SDA/SCL
pin arguments (`runs/leaderboard/live_arduino_skills/prompts/bme280_read_i2c.human_expert.1.md:21-24`).

The generated code uses `Wire.begin()` without pin arguments
(`runs/leaderboard/live_arduino_skills/sources/bme280_read_i2c.human_expert.1/bme280_read_i2c.ino:138-141`),
reads temperature and humidity while discarding pressure bytes
(`runs/leaderboard/live_arduino_skills/sources/bme280_read_i2c.human_expert.1/bme280_read_i2c.ino:92-111`),
compensates temperature and humidity
(`runs/leaderboard/live_arduino_skills/sources/bme280_read_i2c.human_expert.1/bme280_read_i2c.ino:114-135`),
and prints only those two values
(`runs/leaderboard/live_arduino_skills/sources/bme280_read_i2c.human_expert.1/bme280_read_i2c.ino:145-158`).
The serial logs show the requested values for both variants:
24.50 C / 55.00% (`runs/leaderboard/live_arduino_skills/workspace/bme280_read_i2c.human_expert.1/if_1/cases/bme280-read-i2c-wokwi-mega/artifacts/serial/scenario_a.serial.log:1-3`)
and 31.00 C / 42.00%
(`runs/leaderboard/live_arduino_skills/workspace/bme280_read_i2c.human_expert.1/if_1/cases/bme280-read-i2c-wokwi-mega/artifacts/serial/scenario_b.serial.log:1-3`).

The hidden YAML/oracle expects pressure in addition to temperature and humidity
(`tasks/arduino_mega/level2/bme280_read_i2c.yaml:24-31`,
`tasks/arduino_mega/level2/bme280_read_i2c.yaml:35-40`).
The benchmark recorded BF with reason "serial log is missing BME280 pressure
near 101325 Pa" (`runs/leaderboard/live_arduino_skills/attempts.jsonl:16`).

My predicted verdict from the frozen prompt and code is BC. The code satisfies
the humidity/temperature prompt, and the missing pressure is only a hidden
oracle expectation. Conclusion: suspected false fail due prompt/oracle mismatch.

## Undetermined

None.

---

## Independent Re-verification & Resolution (Claude, 2026-06-19)

I independently reproduced the two flagged discrepancies from the frozen prompts,
the task YAMLs, and the validator source, and **confirmed both are real false
fails** with a common root cause. I also re-verified the BC verdicts for false
passes (spot-checked the highest-risk ESP-IDF sensor tasks — PIR reads GPIO 14
and branches; mpu6050 does real I2C register reads) and found none.

### Root cause (confirmed)
All six BME280 tasks deliberately judge a **per-platform 2-of-3 subset**, stated
in their frozen prompts:
- Arduino i2c/spi → temperature + humidity (`tasks/arduino_mega/level2/bme280_read_*.prompt.md:1`)
- ESP-IDF i2c/spi → temperature + pressure, explicitly "intentionally judges
  pressure and temperature" (`tasks/esp32s3_espidf/level2/bme280_read_*.prompt.md:3`)
- Zephyr i2c/spi → temperature + humidity (`tasks/zephyr_nano33ble/level2/bme280_read_*.prompt.md`)

But `validate_bme280_environment` always required temperature + humidity and
checked pressure whenever available (falling back to the chip's
`variant_attrs`, which always carry all three) — so it scored all three on every
platform. Git history confirms the stale-oracle direction: the ESP-IDF prompt's
"intentionally judges pressure and temperature" line was added in `b1b4ec3`
(2026-06-15 13:20) ~3h **after** the YAML's `expected_humidity_rh` (`a0b7e36`,
10:32); the prompt scope was updated, the oracle was not. This violated the
benchmark's core invariant (a model may only be scored on what its frozen prompt
specifies).

### Fix applied
- `bench/validators/__init__.py`: `validate_bme280_environment` now honors a
  `judged_quantities` param naming exactly which of temperature/humidity/pressure
  to score; absent it, the legacy behavior (temp+humidity always, pressure when
  available) is preserved for backward compatibility.
- The six BME280 task YAMLs now set `judged_quantities` to match their prompts
  (Arduino/Zephyr `[temperature, humidity]`, ESP-IDF `[temperature, pressure]`).
  Verified the param propagates to all 12 variant resolutions via `deep_merge`.
- Tests: `tests/test_bme280_variant_support.py` (subset passes when the
  un-judged dimension is absent; still fails when a judged dimension is missing).
- End-to-end: re-judged the exact `bme280_read_i2c.human_expert.1` source
  (humidity+temperature) through the real build→Wokwi→oracle pipeline with the
  new YAML — it now scores **BC** (was BF "missing pressure"). Full offline suite
  green (401 tests).

Net: both suspected false fails are resolved; the BME280 oracles now match their
frozen prompts on all three platforms.

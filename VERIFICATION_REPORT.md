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

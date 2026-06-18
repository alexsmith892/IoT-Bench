# Zephyr / Renode fidelity ledger

A single auditable map of **what a BC verdict on the `zephyr_nano33ble` platform
certifies — and what it does not**. Per-prompt caveats and the oracle list live
elsewhere (`docs/zephyr-task-status.md`, `docs/zephyr-oracle-inventory.md`); this
file consolidates the *modeling shortcuts* (surrogates) so the "solved the
modeled task, not real silicon" boundary is readable in one place.

## Two irreducible ceilings (apply to every task)

1. **Resistant, not provably ungameable.** Oracles are hardened against every
   gaming vector we test (constant output, fixed frequency/pitch, schedule
   replay, hardcoded display, timer-only unlock — see
   `tests/test_adversarial_static.py`) via behavior-distinct simulation variants
   and stimulus→output correlation. "No tested vector games it" is not a proof
   that none can.
2. **Simulated task, not hardware.** A pass certifies the firmware behaves
   correctly against the *Renode model* of the fixture. It does not certify real
   nRF52840 silicon, real sensor electrical/timing behavior, or analog accuracy.
   Renode runs are deterministic in virtual time (byte-identical across runs), so
   a pass is reproducible — but reproducibility is not hardware fidelity.

Renode-wide modeling facts that shape every verdict: CPU is pinned at 2 MIPS
(per-task override via `simulation.performance_mips`); GPIO is two unidirectional
nets (a pull-up *release* is invisible to a model — only push-pull output edges
are seen); the VCD is *synthesized* from a GPIO-transition hook; there is no
stock SAADC or trustworthy PWM model. Detail: `.agent-context/PLATFORMS.md`,
`docs/renode-spike.md`.

## Surrogate families

| Surrogate family | Representative tasks | The shortcut | A pass **certifies** | A pass does **not** certify |
|---|---|---|---|---|
| **Stretched single-wire bit-bang** | `dht11_read`, `dht11_read_button_display`, `ds18b20_heat_alarm` | CPU MIPS raised per task (DHT11=8, DS18B20=64) so `k_busy_wait`/`k_cycle_get_32` resolve a *stretched* version of the protocol bit timing; DS18B20 read bits are driven on the slot's falling edge and held for the whole slot (readback independent of busy-wait stretch). | The firmware drives/decodes the one-wire **protocol structure** (reset, write slots, read slots, CRC) correctly. | Real microsecond-level line timing, slew, or that the same code meets the sensor's real datasheet windows on hardware. |
| **Binary / level analog (SAADC C# model)** | `tmp36_read`, `photoresistor_nightlight`, `sensor_water_level_display`, `lcd1602_auto_brightness_control`, `joystick_buzzer_pitch` | No stock SAADC; analog is the `bench/chips/saadc/` C# model fed raw counts via scenario controls. Sensors are voltage/level surrogates, not physical transducers. | The firmware reads the ADC channel and reacts to the **commanded level** with the correct threshold/mapping behavior, distinguished across variants. | Real transducer transfer curves, noise, reference-voltage accuracy, or self-heating. |
| **Active-high digital event sensors** | `sensor_pir_human_motion`, `hcsr501_motion_alarm`, `tilt_detection_alarm`, `clap_switch` | Motion/tilt/clap are **active-high digital inputs** toggled by the scenario, not analog/acoustic transducers. | The firmware responds to the **event edge** (motion present / tilt / clap) with the correct output, gated by stimulus→output correlation. | Detection sensitivity, debounce against real sensor noise, or analog thresholding. |
| **Software-PWM / busy-wait frequency** | `breathing_led`, `buzzer_doorbell`, `buzzer_button`, `buzzer_toggle_led_freq`, `hcsr04_find_distance`, `parking_sensor`, `reverse_parking_sensor`, `buzzer_laser_tripwire` | nRF PWM is not modeled for pitch/frequency; tones/brightness are produced by busy-wait toggling at 2 MIPS and judged by `frequency_windows`/`pwm_breathing`/`window_ratios`. Frequency bands are tuned to the 2 MIPS busy-wait stretch (keep them strict; retune **only** from measured VCD). | The firmware produces the correct **relative** frequency/duty structure and ordering (e.g. 1/2/4 Hz steps, breathing ramp, buzzer-on windows). | Exact audio Hz on hardware, PWM resolution, or that a frequency band matches a real timer/PWM peripheral. |
| **Matrix keypad cross-point model** | `16key_keypad`, `safebox`, `safebox_display` | `bench/chips/keypad/MatrixKeypad.cs` models the cross-point electrically (rows driven low, columns read). Columns are re-asserted with a real edge every scan to work around Renode's edge-only GPIO input + de-dup (the former `safebox_display` boot quirk, fixed 2026-06-18). | The firmware scans the matrix and decodes the **exact pressed sequence** (relay window oracles + exact LCD echo on `safebox_display`). | Contact bounce, ghosting/N-key rollover (single-key-at-a-time scenarios), or real switch timing. |
| **HD44780 LCD over GPIO (decoded from VCD)** | `lcd1602_display_hello_world`, `*_display` tasks | The 4-bit LCD bus is decoded from the synthesized GPIO VCD into text frames (`lcd_text`/`lcd_text_sequence`). | The firmware drives the **HD44780 nibble/RS protocol** to produce the expected on-screen text/sequence. | Controller timing margins, busy-flag polling vs. fixed delays, or contrast/voltage behavior. |
| **I2C/SPI sensor models** | `mpu6050_read_i2c`, `bme280_read_i2c`, `bme280_read_spi`, `ds1307_rtc`, `lsm9ds1_read_i2c` (addition) | Custom C# chips (`bench/chips/bme280/`, `mpu6050/`) or model registers; I2C uses legacy `nordic,nrf-twi` (Renode lacks TWIM/EasyDMA). DS1307 is read-and-print of a pre-seeded time (no temp oracle). | The firmware performs the correct **bus transactions** and converts/reports register values (incl. BME280 pressure), distinguished across variants. | EasyDMA/TWIM behavior, real bus electrical timing, or sensor calibration accuracy. |

## How to extend this ledger

When adding a task, place it under the surrogate family whose modeling shortcut
it relies on (or add a family if genuinely new), and state plainly what its
oracle does and does not pin. If a task uses no surrogate (pure digital GPIO/
timing, e.g. `blink_led_1hz`, `button_status_count`), it needs no row here — its
verdict certifies the modeled behavior with only the two global ceilings above.

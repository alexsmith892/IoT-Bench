# Renode/Zephyr Phase 0 Spike Findings (2026-06-11)

> Historical note: this file records the initial hand-built spike that shaped
> the backend. Current task maturity lives in
> [zephyr-task-status.md](zephyr-task-status.md). Since this spike, the harness
> has added generated `.repl`/`.resc` cases, button/PIR scenario injection,
> custom SAADC support, custom protocol models for the supported sensor
> families, and broad Zephyr/Renode live coverage. Treat the numbered gotchas
> below as historical design constraints unless a current status page says the
> limitation still applies.

One blink case was hand-built end to end: Zephyr firmware for
`arduino_nano_33_ble` (nRF52840), simulated headless in Renode, with UART
captured to a serial log and GPIO transitions synthesized into a
Wokwi-shaped VCD. The unmodified `waveform_frequency` validator judged the
1 Hz reference **BC** and a 2 Hz variant **BF**
(`D0 HIGH duration 0.250031s is outside tolerance`). These findings are the
basis for the Renode backend (Phases 1+).

## Verified toolchain

| Tool | Version / location |
|---|---|
| Renode | v1.16.1.19220 (.NET 8), `C:\Program Files\Renode\renode.exe` (not on PATH) |
| west | v1.5.0, `C:\Users\alexs\zephyrproject\.venv\Scripts\west.exe` (works without venv activation) |
| Zephyr | `C:\Users\alexs\zephyrproject\zephyr` @ `c49b758d879` (v4.4.0-dev) |
| Zephyr SDK | 1.0.1 minimal + `arm-zephyr-eabi` 14.3.0 at `C:\Users\alexs\zephyr-sdk-1.0.1` (installed during this spike via `west sdk install`) |
| cmake | `C:\Program Files\CMake\bin` - **not on PATH in non-interactive shells** |
| ninja | `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ninja-build.Ninja_...` - not on PATH either |

The harness must prepend cmake/ninja to PATH (or accept configured paths)
when invoking west; `doctor` must check all of the above.

## Acceptance results

- **BC/BF with unmodified validators**: yes (see above), via
  `validate-artifacts --task blink_led_1hz --case ... --allow-unverified-artifacts`.
- **Determinism**: two consecutive headless runs produced byte-identical
  VCD and UART logs (SHA256 equal).
- **VCD resolution**: 1 µs timestamps from
  `machine.ElapsedVirtualTime.TimeElapsed.TotalMicroseconds`. A 1 Hz blink
  measured 1.000061 s periods, duty 0.5000.
- **High-rate fidelity**: a tight `k_busy_wait(500)` toggle loop produced
  9,358 transitions in 2 s virtual (~4.7 kHz) with no event loss; the hook
  scales to PWM-ish rates. (Note: `k_busy_wait` timing in Renode came out
  ~2x fast — 200–300 µs deltas — virtual-time CPU pacing differs from real
  silicon; sleep-based timing via the RTC is accurate.)
- **Wall-clock cost**: ~16–18 s per run for 2–6 s virtual time, of which
  ~4 s is Renode startup. Zephyr build: ~42 s warm (22 s CMake configure +
  20 s compile), ~5 min on a fully cold cache.

## Working invocation

```powershell
& "C:\Program Files\Renode\renode.exe" --disable-xwt --console -e "include @C:\path\case.resc"
```

`.resc` skeleton that worked (key lines):

```
using sysbus
mach create "spike"
machine LoadPlatformDescription @<case>.repl   # derived from arduino_nano_33_ble.repl
sysbus LoadELF @<build>\zephyr\zephyr.elf      # sets PC/SP from ELF automatically
cpu VectorTableOffset 0x10000                  # code_partition offset on this board
uart0 CreateFileBackend @uart.log
python """ ...GPIO hook (below)... """
emulation RunFor "6"                           # seconds of virtual time
python """ write_vcd() """
quit
```

## The GPIO→VCD hook

Attach a probe (`Miscellaneous.LED` works as a universal GPIO receiver; the
board repl already has `led_red` on gpio0 pin 24) and hook `StateChanged`
from a monitor `python """..."""` block (IronPython 2):

```python
machine = monitor.Machine
led = machine["sysbus.gpio0.led_red"]
events = [(0, 1 if led.State else 0)]
def on_state(led_obj, state):
    t = machine.ElapsedVirtualTime.TimeElapsed
    events.append((int(t.TotalMicroseconds), 1 if state else 0))
led.StateChanged += on_state
```

Buffer events in memory and write the VCD at the end, **coalescing
same-timestamp events (last value wins) and deduping same-value runs** —
pin configuration produces a 1→0 glitch pair at the same µs tick, and
`bench/vcd.py:build_segments` rejects non-strictly-increasing timestamps.
`machine.ElapsedVirtualTime` is a `TimeStamp`; the interval is its
`.TimeElapsed`. Exceptions inside the hook abort the whole emulation
(exit code 82) — harness-generated hook code must be defensive.

## Gotchas that shape Phases 1–4

1. **Paths with spaces break Zephyr builds.** This repo lives at
   `...\! IoT\IoT-Bench`; `kconfig.cmake` fails on the space. The backend
   must stage app sources to a space-free build dir (e.g. under
   `%LOCALAPPDATA%`) and copy `zephyr.elf` back into the case's
   `artifacts/build/`.
2. **UART model mode mismatch.** `nrf52840.repl` instantiates
   `UART.NRF52840_UART` with `easyDMA: true` (UARTE), but the Zephyr board
   dts uses the legacy `nordic,nrf-uart` driver → TXD writes at 0x51C went
   unhandled and the log stayed empty. Fix: the case `.repl` derives from
   the board repl and overrides `uart0: easyDMA: false`. Serial logs are
   plain text, no timestamps (assumption preserved); first line is the
   Zephyr boot banner.
3. **No PWM or stock SAADC models** in Renode's `nrf52840.repl`. The harness
   now provides a custom IoT-Bench SAADC model for analog tasks; hardware-PWM
   tasks (breathing LED) still need a PWM model or a carefully documented
   simulator surrogate. GPIO, GPIOTE, RTC, TIMER, TWI (I2C), SPI, UART models
   exist.
4. **SVD from URL**: `nrf52840.repl` runs
   `ApplySVD @https://dl.antmicro.com/...NRF52840.svd.gz` (first run
   downloads, then cached). It only adds register names to log messages;
   for offline/deterministic runs the case repl should neutralize it or the
   doctor should pre-fetch.
5. **ELF link offset**: firmware links at the `code_partition` (0x10000,
   after the SAM-BA bootloader region); `cpu VectorTableOffset 0x10000` is
   required (LoadELF alone sets PC/SP but not VTOR).
6. **Renode exit code** is 82 on `quit` after a crashed emulation; a clean
   run exits 0. The backend should treat nonzero exit + missing artifacts
   as IF with `failure_source: simulator`.
7. **Button injection**: attach `Miscellaneous.Button @ gpioX <pin>` in the
   case repl and drive `Press`/`Release` from timed `.resc` steps. This is now
   exercised by the button, PIR, buzzer, and debounce Zephyr cases.
8. **Digital sensor surrogates**: Renode-backed Zephyr coverage now uses the
   same GPIO-button injection path for simple digital sensors whose useful
   benchmark behavior is a binary stimulus. This supports `hcsr501_motion_alarm`,
   `tilt_detection_alarm`, `clap_switch`, and the button side of
   `buzzer_toggle_led_freq` without adding unsound placeholder peripheral
   models.
9. **Canonical task coverage status has changed since the spike.** HC-SR04,
   DHT11, DS18B20, BME280-SPI, and other modeled peripherals now have generated
   Zephyr cases. Current maturity and scoring exclusions live in
   `zephyr-task-status.md` and `zephyr_nano33ble-evidence.json`, not in this
   historical note. `lsm9ds1_read_i2c` remains an IoT-Bench addition for the
   Nano 33 BLE onboard IMU, not an upstream canonical task.

Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read temperature and relative humidity from a DHT11 sensor and print both
values to the serial console. If the 40-bit DHT11 frame fails checksum
validation, print an error message instead of reporting stale data.

Use the canonical devicetree alias `data-dht11` for the DHT11 data GPIO.
Implement the application in `src/main.c` with a `main` function. Use only
Zephyr core APIs and in-tree drivers; do not use external modules or
third-party libraries.

Simulator timing note: this task runs in a logic simulator, not on real
hardware, and the DHT11 single-wire waveform is deliberately stretched by
roughly 10-20x relative to the datasheet so the simulator's virtual-time
resolution (~30 us) can resolve it. Pace your bit-banging to the simulated
scale, not the datasheet microseconds: hold the start-low for ~20 ms, then
release and read the 40-bit frame where each data bit is carried in the width
of its high pulse (logic 0 ≈ 0.5 ms high, logic 1 ≈ 1.5 ms high). Sample the
high-pulse width and treat anything longer than ~1 ms as a 1. Use wide
tolerances rather than exact edge timing.

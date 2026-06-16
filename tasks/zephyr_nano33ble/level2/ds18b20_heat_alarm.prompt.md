Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the temperature from a DS18B20 sensor. If the reading exceeds 30 degrees C,
flash the LED and sound the active buzzer; otherwise keep both outputs off.

Use canonical devicetree aliases `data-ds18b20` for the DS18B20 data GPIO,
`my-led` for the LED, and `my-buzzer` for the buzzer. Implement the application
in `src/main.c` with a `main` function. Use only Zephyr core APIs and in-tree
drivers; do not use external modules or third-party libraries.

Simulator timing note: this task runs in a logic simulator, not on real
hardware, and the DS18B20 1-Wire waveform is deliberately stretched by roughly
10x relative to the datasheet so the simulator's virtual-time resolution
(~30 us) can resolve it. Pace your 1-Wire bit-banging to the simulated scale,
not the datasheet microseconds: a reset is a low of ~2 ms; a write-0 holds the
line low ~400 us and a write-1 ~30 us; for a read slot pull the line low
briefly (~60 us), release it, then sample — the sensor drives the response bit
and holds it for the whole slot, so any sample taken mid-slot is valid. Use
wide tolerances rather than exact edge timing. The sensor returns a standard
9-byte scratchpad (temperature in bytes 0-1 as a signed 1/16 °C value) with a
trailing CRC8.

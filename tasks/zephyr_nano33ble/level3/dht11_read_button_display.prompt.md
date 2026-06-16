Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Implement a GPIO interrupt on the push button. Each time the button is pressed,
trigger a DHT11 start condition, read the returned 40-bit frame, validate the
checksum, parse temperature and relative humidity, and display the readings on
the LCD1602 in two rows:

Temp: {X.X}C
RH: {X.X}%

Use canonical devicetree aliases `my-button`, `data-dht11`, `D-7`, `D-6`,
`D-5`, `D-4`, `RS`, and `E`. Implement the application in `src/main.c` with a
`main` function. Use only Zephyr core APIs and in-tree drivers; do not use
external modules or third-party libraries.

Simulator timing note: this task runs in a logic simulator, not on real
hardware, and the DHT11 single-wire waveform is deliberately stretched by
roughly 10-20x relative to the datasheet so the simulator's virtual-time
resolution (~30 us) can resolve it. Pace your bit-banging to the simulated
scale, not the datasheet microseconds: hold the start-low for ~20 ms, then
release and read the 40-bit frame where each data bit is carried in the width
of its high pulse (logic 0 ≈ 0.5 ms high, logic 1 ≈ 1.5 ms high). Sample the
high-pulse width and treat anything longer than ~1 ms as a 1. Use wide
tolerances rather than exact edge timing. Re-read the sensor on each button
press so the displayed values track the current temperature and humidity.

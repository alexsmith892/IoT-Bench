Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Blink the board's red LED at a frequency of 1 Hz (toggle every 500 ms).
The red LED is on GPIO port 0, pin 24 (devicetree alias `led0`).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.

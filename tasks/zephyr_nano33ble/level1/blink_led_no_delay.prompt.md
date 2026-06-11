Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Blink the board's red LED at a frequency of 1 Hz using a non-blocking
method: do not call blocking sleep/delay APIs (`k_msleep`, `k_sleep`,
`k_usleep`, `k_busy_wait`); schedule the toggles from elapsed time
(e.g. `k_uptime_get`).
The red LED is on GPIO port 0, pin 24 (devicetree alias `led0`).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.

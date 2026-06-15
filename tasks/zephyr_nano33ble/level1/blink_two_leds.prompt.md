Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Blink two GPIO-connected LEDs at different frequencies without using blocking
sleep or busy-wait calls in the main timing loop. LED 1 should toggle every
500 ms (1 Hz blink), and LED 2 should toggle every 250 ms (2 Hz blink).

LED 1 is on GPIO port 0, pin 24. LED 2 is on GPIO port 0, pin 16.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.

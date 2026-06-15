Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the state of a pull-down button and turn on an active buzzer while the
debounced button state is pressed. Implement software debouncing so short
bounces do not cause the buzzer output to chatter.

The button is on GPIO port 1, pin 11 and is wired active-high. The buzzer is
on GPIO port 1, pin 12 and is active-high.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.

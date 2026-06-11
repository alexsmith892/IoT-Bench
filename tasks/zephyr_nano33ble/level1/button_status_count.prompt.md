Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the state of a button and count the number of times it has been
pressed. Each time a new press is detected, print the updated count to the
serial console on its own line (e.g. `1`, then `2`, then `3`).
The button is on GPIO port 1, pin 11 and is wired active-high: the pin
reads 1 while the button is held and 0 when released.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries.

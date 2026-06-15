Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the state of a pull-down button and print `Button Pressed!` to the
serial console when a new press is detected. Print once per press, not
continuously while the button is held.

The button is on GPIO port 1, pin 11 and is wired active-high: the pin reads
1 while the button is held and 0 when released.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries.

Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the digital output of an HC-SR501 human presence sensor, where the
output is HIGH when human motion is detected and LOW when it is not.
Print "Motion Detected!" to the serial console when motion is detected,
and "No Motion Detected!" when no motion is detected (one line per state
change). The sensor output is on GPIO port 1, pin 15.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries.

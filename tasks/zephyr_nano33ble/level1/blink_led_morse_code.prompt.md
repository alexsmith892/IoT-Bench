Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Blink the board's red LED to spell SOS in Morse code. Use a 200 ms dot unit:
three short pulses, three long pulses, and three short pulses. Leave the LED
off between pulses and repeat the pattern.

Use the canonical devicetree alias `my-led` for the LED. In the local
Renode fixture this maps to GPIO port 0, pin 24.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.

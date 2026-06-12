Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

An LCD1602 character display (HD44780-compatible) is connected in 4-bit
mode. Initialize it and display "Hello World" centered on the first line.

Wiring (GPIO port.pin):
- RS: P1.12
- E:  P1.14
- D4: P1.15
- D5: P1.13
- D6: P0.21
- D7: P0.27
(RW is tied to ground; write-only.)

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.
Drive the display directly at pin level (no display driver subsystem).

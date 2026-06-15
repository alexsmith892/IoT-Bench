Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Build a reaction timer: a button starts the timer and a digital shock
sensor stops it; show the elapsed time on an LCD1602.

The start button is on GPIO port 1, pin 11 and is wired active-high (reads
1 while held). The shock sensor output is on GPIO port 1, pin 10 and goes
HIGH when a shock is detected. Start timing when the button is first
pressed; stop when the shock sensor goes HIGH; then display the elapsed
time in milliseconds on the LCD in the form `<n> ms` (e.g. `352 ms`).

The LCD1602 is wired in 4-bit mode: RS on P1.12, E on P1.14, D4 on P1.15,
D5 on P1.13, D6 on P0.21, D7 on P0.27 (RW grounded).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.
Drive the LCD directly at pin level (HD44780 4-bit protocol).

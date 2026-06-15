Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Demonstrate a timer-based temperature logger: sample the TMP36's raw ADC
reading every 1 second and log it to an LCD1602, with a push button that
resets the log.

Set up a 1-second periodic timer and keep a counter of how many times it
has expired. Every time it expires, sample ADC input AIN0 (P0.04) with
the Zephyr ADC API at 12-bit resolution and append a new log line to the
LCD in the form:

Temp #<counter>: <raw ADC reading> F

The most recent reading is always displayed on the bottom row, and the
previous reading shifts up (the LCD has 2 rows, so the previous line is
on row 1 and the newest on row 2). Additionally, implement a GPIO
interrupt on the push button (GPIO port 1, pin 11, active-high): when
pressed, reset the counter to start from 1 and clear the LCD.

The LCD1602 is wired in 4-bit mode: RS on P1.12, E on P1.14, D4 on P1.15,
D5 on P1.13, D6 on P0.21, D7 on P0.27 (RW grounded).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/adc.h`,
`zephyr/drivers/gpio.h`, `zephyr/kernel.h`); do not use external modules
or third-party libraries. Drive the LCD directly at pin level (HD44780
4-bit protocol).

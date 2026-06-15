Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Demonstrate a temperature logger: every time a push button is pressed,
sample the analog output of a TMP36 temperature sensor and display the
reading in Fahrenheit on an LCD1602.

Implement a GPIO interrupt on the button (GPIO port 1, pin 11,
active-high: rising edge = press). On each press, clear the LCD, sample
the TMP36 on ADC input AIN0 (P0.04) with the Zephyr ADC API at 12-bit
resolution (full scale 4095 counts = 3.3 V), convert to Celsius
(C = (Vout - 0.5 V) * 100) and then to Fahrenheit (F = C * 9 / 5 + 32),
and display:

Temp: <value> F

The LCD1602 is wired in 4-bit mode: RS on P1.12, E on P1.14, D4 on P1.15,
D5 on P1.13, D6 on P0.21, D7 on P0.27 (RW grounded).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/adc.h`,
`zephyr/drivers/gpio.h`, `zephyr/kernel.h`); do not use external modules
or third-party libraries. Drive the LCD directly at pin level (HD44780
4-bit protocol).

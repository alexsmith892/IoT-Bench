Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Use an analog water level sensor to display a "Water Level" bar graph on
an LCD1602.

The sensor is connected to ADC input AIN0 (P0.04); higher water level
produces higher ADC counts. Read it with the Zephyr ADC API at 12-bit
resolution (full scale 4095 counts) at least every 100 ms. Show the text
`Water Level` on the LCD's first row, and on the second row draw a bar of
`#` characters proportional to the current level: 16 characters at full
scale (i.e. bar length = reading * 16 / 4096, at least 1 character when
the reading is non-zero). Redraw the bar when the level changes.

The LCD1602 is wired in 4-bit mode: RS on P1.12, E on P1.14, D4 on P1.15,
D5 on P1.13, D6 on P0.21, D7 on P0.27 (RW grounded).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/adc.h`,
`zephyr/drivers/gpio.h`, `zephyr/kernel.h`); do not use external modules
or third-party libraries. Drive the LCD directly at pin level (HD44780
4-bit protocol).

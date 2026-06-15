Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Scan a 16-key (4x4) matrix keypad and print one line to the serial console
each time a key is pressed, in this shape:

Key: <k>

where <k> is the key legend. The keypad uses the standard layout (row 1:
`1 2 3 A`, row 2: `4 5 6 B`, row 3: `7 8 9 C`, row 4: `* 0 # D`). The four
row lines are on GPIO port 1, pins 11, 12, 15, 13 (rows 1-4 in that
order) and the four column lines are on GPIO port 1 pin 14, and GPIO
port 0 pins 23, 21, 27 (columns 1-4 in that order).

Drive the row lines as outputs and read the column lines as inputs.
Columns idle HIGH; while a key is held and its row is driven LOW, the
key's column reads LOW. Implement a scanning routine (drive one row low
at a time and read the columns), detect each new key press exactly once,
and print it.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries.

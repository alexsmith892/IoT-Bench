Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Build a safebox lock: read a 4-digit password from a 4x4 matrix keypad and
connect (energize) the lock relay only when the entered code matches the
password "1234". After any 4 keys have been entered, compare against the
password: on a match, drive the relay HIGH (unlocked) and keep it high; on
a mismatch, keep the relay LOW and start over with the next 4 keys.

The keypad uses the standard layout (row 1: `1 2 3 A`, row 2: `4 5 6 B`,
row 3: `7 8 9 C`, row 4: `* 0 # D`). The row lines are on GPIO port 1,
pins 11 and 12 (rows 1-2; rows 3-4 are not used by the tests) and the
column lines are on GPIO port 1 pin 14 and GPIO port 0 pins 23 and 21
(columns 1-3). Drive rows as outputs and read columns as inputs: columns
idle HIGH, and while a key is held with its row driven LOW the key's
column reads LOW. Detect each key press exactly once (scan with edge
detection).

The lock relay is on GPIO port 0, pin 13 (active-high, LOW = locked).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.

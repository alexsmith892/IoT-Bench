Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Build a safebox lock with a status display: read a 4-digit password from a
4x4 matrix keypad, drive the lock relay, and show the entry and result on
an LCD1602.

The password is "1234". After any 4 keys have been entered, compare
against the password and update an LCD1602 display (4-bit mode) with two
rows:

Input: <the 4 keys entered>
Status: <Success|Fail>

On a match also drive the relay HIGH (unlocked) and keep it high; on a
mismatch keep the relay LOW and start over with the next 4 keys.

The keypad uses the standard layout (row 1: `1 2 3 A`, row 2: `4 5 6 B`,
row 3: `7 8 9 C`, row 4: `* 0 # D`). The row lines are on GPIO port 1,
pins 11 and 2 (rows 1-2; rows 3-4 are not used by the tests) and the
column lines are on GPIO port 1 pins 1 and 8, and GPIO port 0 pin 23
(columns 1-3). Drive rows as outputs and read columns as inputs: columns
idle HIGH, and while a key is held with its row driven LOW the key's
column reads LOW. Detect each key press exactly once.

The lock relay is on GPIO port 0, pin 13 (active-high, LOW = locked).
The LCD1602 is wired in 4-bit mode: RS on P1.12, E on P1.14, D4 on P1.15,
D5 on P1.13, D6 on P0.21, D7 on P0.27 (RW grounded).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.
Drive the LCD directly at pin level (HD44780 4-bit protocol).

Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the temperature from a DS18B20 sensor. If the reading exceeds 30 degrees C,
flash the LED and sound the active buzzer; otherwise keep both outputs off.

Use canonical devicetree aliases `data-ds18b20` for the DS18B20 data GPIO,
`my-led` for the LED, and `my-buzzer` for the buzzer. Implement the application
in `src/main.c` with a `main` function. Use only Zephyr core APIs and in-tree
drivers; do not use external modules or third-party libraries.

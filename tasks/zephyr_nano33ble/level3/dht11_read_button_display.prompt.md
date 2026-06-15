Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Implement a GPIO interrupt on the push button. Each time the button is pressed,
trigger a DHT11 start condition, read the returned 40-bit frame, validate the
checksum, parse temperature and relative humidity, and display the readings on
the LCD1602 in two rows:

Temp: {X.X}C
RH: {X.X}%

Use canonical devicetree aliases `my-button`, `data-dht11`, `D-7`, `D-6`,
`D-5`, `D-4`, `RS`, and `E`. Implement the application in `src/main.c` with a
`main` function. Use only Zephyr core APIs and in-tree drivers; do not use
external modules or third-party libraries.

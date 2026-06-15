Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read temperature and relative humidity from a BME280 sensor over the SPI bus
and print both values to the serial console. Convert the BME280 compensation
registers into human-readable units; do not print raw ADC counts.

Use the canonical devicetree sensor alias `my_sensor` for the SPI BME280.
Implement the application in `src/main.c` with a `main` function. Use only
Zephyr core APIs and in-tree drivers; do not use external modules or
third-party libraries.

Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read temperature and relative humidity from a DHT11 sensor and print both
values to the serial console. If the 40-bit DHT11 frame fails checksum
validation, print an error message instead of reporting stale data.

Use the canonical devicetree alias `data-dht11` for the DHT11 data GPIO.
Implement the application in `src/main.c` with a `main` function. Use only
Zephyr core APIs and in-tree drivers; do not use external modules or
third-party libraries.

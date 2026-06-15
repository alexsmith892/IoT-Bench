Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the analog output of a TMP36 temperature sensor, where the output
voltage is linearly proportional to the temperature in degrees Celsius
(10 mV per degree with a 500 mV offset: C = (Vout - 0.5 V) * 100), and
print the temperature value in Celsius to the serial console repeatedly
(several times per second), one value per line with one decimal place.

The TMP36 output is connected to ADC input AIN0 (P0.04). Read it with the
Zephyr ADC API at 12-bit resolution; the ADC full scale corresponds to
3.3 V (i.e. voltage = raw * 3.3 / 4095).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/adc.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries.

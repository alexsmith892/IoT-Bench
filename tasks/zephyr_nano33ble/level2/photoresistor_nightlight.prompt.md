Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Use a photoresistor to check whether the current light level is below a
threshold, and turn on an LED while it is (a nightlight). The
photoresistor divider is connected to ADC input AIN0 (P0.04) and is wired
so that bright light produces LOW ADC counts and darkness produces HIGH
counts. Read it with the Zephyr ADC API at 12-bit resolution (full scale
4095 counts = 3.3 V) and treat readings above half scale (2048 counts,
about 1.65 V) as "dark": turn the LED on while the reading is above the
threshold and off otherwise. Sample continuously (at least every 50 ms).

The LED is on GPIO port 0, pin 24 and is active-high.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/adc.h`,
`zephyr/drivers/gpio.h`, `zephyr/kernel.h`); do not use external modules
or third-party libraries.

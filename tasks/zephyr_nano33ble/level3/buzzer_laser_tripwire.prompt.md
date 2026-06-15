Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

A laser emitter is aimed at a photoresistor; sound an active buzzer while
the beam is blocked.

Drive the laser emitter, on GPIO port 0, pin 21 (active-high), on for the
whole run. The photoresistor divider is connected to ADC input AIN0
(P0.04) and is wired so that the laser hitting it produces LOW ADC counts
and a blocked beam (darkness) produces HIGH counts. Read it with the
Zephyr ADC API at 12-bit resolution (full scale 4095 counts = 3.3 V) and
treat readings above half scale (2048 counts) as "beam blocked": turn the
buzzer on while blocked and off otherwise. Sample continuously (at least
every 50 ms).

The active buzzer is on GPIO port 0, pin 27 (active-high).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/adc.h`,
`zephyr/drivers/gpio.h`, `zephyr/kernel.h`); do not use external modules
or third-party libraries.

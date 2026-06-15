Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Use a joystick's Y axis to change the pitch of a passive buzzer.

The joystick's X axis is on ADC input AIN0 (P0.04, channel 0) and the Y
axis on AIN1 (P0.05, channel 1). Read the Y axis with the Zephyr ADC API
at 12-bit resolution (full scale 4095 counts) at least every 50 ms, and
drive the passive buzzer with a square wave whose frequency scales
linearly with the reading: about 200 Hz near the bottom of the range
(reading ~400) up to about 1800 Hz near the top (reading ~3700). Use
frequency = 100 + reading * 1900 / 4096 Hz (or an equivalent linear
mapping within those endpoints), updating as the reading changes.

The passive buzzer is on GPIO port 0, pin 27; generate the square wave by
toggling that pin in software.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/adc.h`,
`zephyr/drivers/gpio.h`, `zephyr/kernel.h`); do not use external modules
or third-party libraries.

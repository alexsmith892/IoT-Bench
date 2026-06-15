Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Use the ambient light level from a KY-018 photoresistor to automatically
adjust the brightness of an LCD1602 backlight.

The photoresistor divider is connected to ADC input AIN0 (P0.04) and is
wired so that bright light produces LOW ADC counts and darkness produces
HIGH counts. Read it with the Zephyr ADC API at 12-bit resolution (full
scale 4095 counts) at least every 50 ms, and map the reading to a PWM
duty cycle on the backlight level pin K: dim backlight (duty around
reading/4096, i.e. ~5-15%) in bright light, bright backlight (~90%) in
darkness - duty = reading * 100 / 4096 percent is a suitable mapping.
Generate the PWM in software by toggling the K pin with a carrier period
of about 2 ms (500 Hz); do not use a hardware PWM peripheral.

The backlight level pin K is on GPIO port 1, pin 8. The LCD1602 data
interface is wired in 4-bit mode (RS on P1.12, E on P1.14, D4 on P1.15,
D5 on P1.13, D6 on P0.21, D7 on P0.27); initialize the display, but the
exercised behavior is the backlight control.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/adc.h`,
`zephyr/drivers/gpio.h`, `zephyr/kernel.h`); do not use external modules
or third-party libraries.

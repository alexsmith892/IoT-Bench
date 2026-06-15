Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Breathing LEDs mimic the inhale and exhale of a lung by gradually turning
brighter or dimmer over time. The brightness of an LED is controlled by
the PWM duty cycle on its GPIO.

Implement 50 duty cycle levels (2%, 4%, ..., 100%). The duty cycle should
step to the next level every 10 ms, ramping up from 2% to 100% and then
back down, so the breathing frequency is 1 Hz. Generate the PWM in
software by toggling the LED pin (use a carrier period of about 2 ms /
500 Hz and time the on/off phases with `k_busy_wait`); do not use a
hardware PWM peripheral.

The LED is on GPIO port 0, pin 24 and is active-high.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.

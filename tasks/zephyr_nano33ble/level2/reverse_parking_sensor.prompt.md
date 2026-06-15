Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Build a reverse parking aid: use an HC-SR04 ultrasonic sensor to measure
the distance to an obstacle and pulse a passive buzzer faster (higher
frequency) as the object gets closer.

The HC-SR04 TRIG input is on GPIO port 1, pin 11 and ECHO on GPIO port 1,
pin 10: pulse TRIG high for at least 10 us, then time the ECHO pulse
(58 us per centimeter) to get the distance. Measure repeatedly (at least
a few times per second).

Drive the passive buzzer, on GPIO port 0, pin 27, with a software square
wave at frequency = 2500 - 20 * distance_cm Hz, toggling the pin with
delays, and update the frequency as the distance changes.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.

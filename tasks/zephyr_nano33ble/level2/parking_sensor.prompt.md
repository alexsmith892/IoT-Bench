Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Build a parking sensor: use an HC-SR04 ultrasonic sensor to measure the
distance to an obstacle, turn an LED on while an obstacle is detected
(distance below 100 cm), and drive a passive buzzer with a pitch that
rises as the obstacle gets closer.

The HC-SR04 TRIG input is on GPIO port 1, pin 11 and ECHO on GPIO port 1,
pin 10: pulse TRIG high for at least 10 us, then time the ECHO pulse
(58 us per centimeter) to get the distance. Measure repeatedly (at least
a few times per second).

Drive the passive buzzer, on GPIO port 0, pin 27, with a software square
wave at frequency = 2500 - 20 * distance_cm Hz (so closer objects produce
a higher pitch), toggling the pin with delays. The LED is on GPIO port 0,
pin 24 (active-high); keep it on while the measured distance is below
100 cm.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`); do not use external modules or third-party libraries.

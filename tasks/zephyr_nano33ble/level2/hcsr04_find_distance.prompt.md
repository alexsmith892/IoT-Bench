Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Use an HC-SR04 ultrasonic sensor to measure distance and print it to the
serial console repeatedly (several times per second), one measurement per
line, in this shape:

Distance: <d> cm

where <d> is the distance in centimeters. The sensor's TRIG input is on
GPIO port 1, pin 11 and its ECHO output on GPIO port 1, pin 10. For each
measurement, drive TRIG high for at least 10 microseconds and then low;
the sensor then raises ECHO, holding it high for 58 microseconds per
centimeter of distance. Time the ECHO pulse width (e.g. with
`k_cycle_get_32` / `k_cyc_to_us_floor32`, or `k_uptime_ticks`) and compute
distance = pulse_width_us / 58.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries.

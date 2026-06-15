Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Use a GY-521 (MPU6050) accelerometer to count steps based on movement
spikes, and print the running step count to the serial console: each time
a new step is detected, print the updated count on its own line (e.g.
`1`, then `2`, then `3`).

Wake the MPU6050 from sleep (clear the SLEEP bit in PWR_MGMT_1, register
0x6B) and sample the Z-axis acceleration (ACCEL_ZOUT_H at 0x3F..0x40,
big-endian, 16384 counts per g at the default +/-2 g range) periodically
(at least every 50 ms). Detect a step as an upward crossing of a
threshold roughly halfway between rest (about 1 g) and a spike (about
1.9 g) - e.g. count one step each time the reading rises above ~1.45 g
(~23700 counts) after having been below it. The MPU6050 is on the `i2c0`
bus at address 0x68.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/i2c.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries, and do not use Zephyr's sensor subsystem.

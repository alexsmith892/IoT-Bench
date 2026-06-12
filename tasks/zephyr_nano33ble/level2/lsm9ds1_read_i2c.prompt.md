Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the raw accelerometer and gyroscope values from the board's LSM9DS1
IMU over I2C and print them to the serial console repeatedly (a few times
per second), one snapshot per line, in this shape:

Accel: <ax> <ay> <az> Gyro: <gx> <gy> <gz>

Print the raw 16-bit signed counts exactly as read from the sensor's output
registers (accelerometer OUT_X_XL at 0x28..0x2D, gyroscope OUT_X_G at
0x18..0x1D, little-endian); do not convert to physical units and do not
reconfigure the sensor's measurement ranges.
The LSM9DS1 is on the `i2c0` bus at address 0x6B.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/i2c.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries. Communicate with the device directly at register level.

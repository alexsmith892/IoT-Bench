Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the raw accelerometer and gyroscope values from an MPU6050 IMU over
I2C and print them to the serial console repeatedly (a few times per
second), one snapshot per line, in this shape:

Accel: <ax> <ay> <az> Gyro: <gx> <gy> <gz>

Wake the device from sleep first (clear the SLEEP bit in PWR_MGMT_1,
register 0x6B), then print the raw 16-bit signed counts exactly as read
from the sensor's output registers (accelerometer ACCEL_XOUT_H at
0x3B..0x40, gyroscope GYRO_XOUT_H at 0x43..0x48, big-endian); do not
convert to physical units and do not reconfigure the sensor's measurement
ranges. The MPU6050 is on the `i2c0` bus at address 0x68.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/i2c.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries, and do not use Zephyr's sensor subsystem. Communicate with the
device directly at register level.

Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the temperature and relative humidity from a BME280 environmental
sensor over I2C and print them to the serial console repeatedly (a few
times per second), one snapshot per line, in this shape:

Temperature: <t> C Humidity: <h> %

where <t> is in degrees Celsius and <h> is in percent relative humidity,
each printed with at least one decimal place. Read the sensor's
calibration registers (0x88..0xA1 and 0xE1..0xE7), configure a
measurement mode, read the raw data registers (0xF7..0xFE), and apply
the BME280 datasheet compensation formulas; do not print raw ADC counts.
The BME280 is on the `i2c0` bus at address 0x76. The bus does not support
repeated-start combined transfers: when reading a register, issue a
separate write transaction (register address) followed by a separate read
transaction (e.g. `i2c_write` then `i2c_read`, not `i2c_write_read` or
`i2c_burst_read`).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/i2c.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries, and do not use Zephyr's sensor subsystem. Communicate with the
device directly at register level. Note that floating-point printf
formatting is not enabled; format decimal values from integer math.

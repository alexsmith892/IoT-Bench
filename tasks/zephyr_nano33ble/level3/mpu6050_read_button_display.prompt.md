Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Each time a push button is pressed, read the accelerometer and gyroscope
from an MPU6050 over I2C and display the values on an LCD1602.

Implement a GPIO interrupt on the button (GPIO port 1, pin 11,
active-high: rising edge = press). On each press, read the raw 16-bit
accel (ACCEL_XOUT_H at 0x3B..0x40) and gyro (GYRO_XOUT_H at 0x43..0x48)
registers (big-endian) and write two rows to the LCD:

Accel: <ax> <ay> <az>
Gyro: <gx> <gy> <gz>

Print the raw signed counts (do not convert units, do not reconfigure the
measurement ranges). Wake the MPU6050 from sleep first (clear the SLEEP
bit in PWR_MGMT_1, register 0x6B). The MPU6050 is on the `i2c0` bus at
address 0x68.

The LCD1602 is wired in 4-bit mode: RS on P1.12, E on P1.14, D4 on P1.15,
D5 on P1.13, D6 on P0.21, D7 on P0.27 (RW grounded).

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/drivers/i2c.h`, `zephyr/kernel.h`); do not use external modules,
third-party libraries, or Zephyr's sensor subsystem. Drive the LCD
directly at pin level (HD44780 4-bit protocol).

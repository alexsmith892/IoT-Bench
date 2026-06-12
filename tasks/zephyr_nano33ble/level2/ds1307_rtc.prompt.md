Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Read the current date and time from the DS1307 RTC module via I2C and print
them to the serial console (for example as YYYY/MM/DD HH:MM:SS). The RTC is
already running with the correct time, so do not set or overwrite the clock
— just read it and report what it says.
The DS1307 is on the `i2c0` bus at address 0x68.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/i2c.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries. Communicate with the device directly at register level.

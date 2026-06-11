Read the current date and time from the DS1307 RTC module via I2C and print them to the serial console (for example as YYYY/MM/DD HH:MM:SS). The RTC is already running with the correct time, so do not set or overwrite the clock — just read it and report what it says.
Use GPIO 20 for SDA and GPIO 21 for SCL.
Use only the Arduino core and its built-in libraries (e.g., Wire, SPI, Serial); do not use any external or third-party libraries. Communicate with sensors and modules directly (register-level / pin-level).

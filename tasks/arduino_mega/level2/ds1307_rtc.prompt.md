Read the current date and time from the DS1307 RTC module via I2C and print them to the serial console (for example as YYYY/MM/DD HH:MM:SS). The RTC is already running with the correct time, so do not set or overwrite the clock — just read it and report what it says.
Use GPIO 20 for SDA and GPIO 21 for SCL.

Use the ambient light intensity (the KY-018 photoresistor) to automatically adjust the brightness of the LCD1602 backlight. Read the analog value from the KY-018 photoresistor, map it to a suitable PWM duty cycle, and control the backlight brightness accordingly.
Photo-resistor: A2. LCD1602: Use GPIO 12,11,4,5,6,7 for RS, E, D4, D5, D6, D7 and GPIO 10 for A.
Use only the Arduino core and its built-in libraries (e.g., Wire, SPI, Serial); do not use any external or third-party libraries. Communicate with sensors and modules directly (register-level / pin-level).

Use the ultrasonic sensor (HC-SR04) to measure distance. The sensor sends out a trigger pulse, and then listens for the echo pulse. The width of the echo pulse is proportional to the distance between the sensor and the obstacle. Calculate the distance based on the timing of the echo return, and print the distance value to the serial console. 
Use GPIO 9 for TRIG and GPIO 10 for ECHO.
Use only the Arduino core and its built-in libraries (e.g., Wire, SPI, Serial); do not use any external or third-party libraries. Communicate with sensors and modules directly (register-level / pin-level).

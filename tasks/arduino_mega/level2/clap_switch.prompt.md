Use the digital sound sensor (which will turn the GPIO to HIGH if the sound level exceeds the threshold) to toggle the relay state on/off.
Sound sensor: A0 for analog output, GPIO 7 for digital output. Relay: GPIO 2.
Use only the Arduino core and its built-in libraries (e.g., Wire, SPI, Serial); do not use any external or third-party libraries. Communicate with sensors and modules directly (register-level / pin-level).

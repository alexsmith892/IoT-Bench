# safebox

Read password input from a 16-key keypad; password is 1234 and matching input drives the relay to unlock. Use keypad rows GPIO 9,10,11,13, columns GPIO 14,8,45,46, and relay GPIO 12. The keypad column is relocated from GPIO 12 to GPIO 8 to free the relay pin; upstream assigns both to GPIO 12, which a scanned matrix cannot share. Columns that upstream lists as GPIO 43/44 are mapped to exposed Wokwi ESP32-S3 DevKitC GPIO 45/46 for simulation.

Implement the solution as an ESP-IDF application for the ESP32-S3 DevKitC-1. Write C/C++ code for `main/main.c` with `void app_main(void)`. Use ESP-IDF driver APIs (`driver/gpio.h`, ADC one-shot, LEDC, I2C/SPI drivers, timers/FreeRTOS as appropriate) and `printf` for serial output. Do not use Arduino APIs or external Arduino libraries such as pinMode, digitalRead, digitalWrite, analogRead, Serial, delay, tone, Wire, SPI, LiquidCrystal, or Keypad.

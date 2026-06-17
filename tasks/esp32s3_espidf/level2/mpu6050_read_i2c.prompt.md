# mpu6050_read_i2c

Read raw accelerometer and gyroscope data from the MPU6050 via I2C and print to serial console. Use GPIO 38 SDA and GPIO 39 SCL. Print each sample as a single line `Accel: <x> <y> <z> Gyro: <x> <y> <z>` using the raw integer counts.

Implement the solution as an ESP-IDF application for the ESP32-S3 DevKitC-1. Write C/C++ code for `main/main.c` with `void app_main(void)`. Use ESP-IDF driver APIs (`driver/gpio.h`, ADC one-shot, LEDC, I2C/SPI drivers, timers/FreeRTOS as appropriate) and `printf` for serial output. Do not use Arduino APIs or external Arduino libraries such as pinMode, digitalRead, digitalWrite, analogRead, Serial, delay, tone, Wire, SPI, LiquidCrystal, or Keypad.

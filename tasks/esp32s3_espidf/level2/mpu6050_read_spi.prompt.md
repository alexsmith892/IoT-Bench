# mpu6050_read_spi

Read raw accelerometer and gyroscope data from the MPU6050 via SPI and print to serial console. Use GPIO 35 SCK, GPIO 37 MISO, GPIO 36 MOSI, GPIO 14 CS. Also read the WHO_AM_I identity register and print each sample as a single line `WHO: 0x<id> Accel: <x> <y> <z> Gyro: <x> <y> <z>` using the raw integer counts.

Implement the solution as an ESP-IDF application for the ESP32-S3 DevKitC-1. Write C/C++ code for `main/main.c` with `void app_main(void)`. Use ESP-IDF driver APIs (`driver/gpio.h`, ADC one-shot, LEDC, I2C/SPI drivers, timers/FreeRTOS as appropriate) and `printf` for serial output. Do not use Arduino APIs or external Arduino libraries such as pinMode, digitalRead, digitalWrite, analogRead, Serial, delay, tone, Wire, SPI, LiquidCrystal, or Keypad.

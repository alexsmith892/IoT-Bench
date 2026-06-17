# mpu6050_read_periodic_display

Every 100ms, read MPU6050 accel/gyro via I2C, average 10 samples, and display raw accel/gyro count rows on LCD1602. Use I2C SDA 9/SCL 10 and LCD RS 38, E 39, D4-D7 40,41,42,21. The fixture includes an unused button on GPIO 2. Display two rows formatted as `Accel: <x> <y>` and `Gyro: <x> <y>` using the raw integer counts.

Implement the solution as an ESP-IDF application for the ESP32-S3 DevKitC-1. Write C/C++ code for `main/main.c` with `void app_main(void)`. Use ESP-IDF driver APIs (`driver/gpio.h`, ADC one-shot, LEDC, I2C/SPI drivers, timers/FreeRTOS as appropriate) and `printf` for serial output. Do not use Arduino APIs or external Arduino libraries such as pinMode, digitalRead, digitalWrite, analogRead, Serial, delay, tone, Wire, SPI, LiquidCrystal, or Keypad.

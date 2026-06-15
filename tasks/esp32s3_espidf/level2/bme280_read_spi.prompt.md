# bme280_read_spi

Read atmospheric pressure and temperature from a BME280 sensor using SPI and print values to serial. Use GPIO 38 SCK, GPIO 40 SDO, GPIO 39 SDI, GPIO 41 CS. This ESP32 task intentionally judges pressure and temperature.

Implement the solution as an ESP-IDF application for the ESP32-S3 DevKitC-1. Write C/C++ code for `main/main.c` with `void app_main(void)`. Use ESP-IDF driver APIs (`driver/gpio.h`, ADC one-shot, LEDC, I2C/SPI drivers, timers/FreeRTOS as appropriate) and `printf` for serial output. Do not use Arduino APIs or external Arduino libraries such as pinMode, digitalRead, digitalWrite, analogRead, Serial, delay, tone, Wire, SPI, LiquidCrystal, or Keypad.

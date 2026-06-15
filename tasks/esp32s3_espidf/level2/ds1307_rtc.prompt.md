# ds1307_rtc

Read the seeded DS1307-compatible RTC date/time over I2C and print it to serial. Use GPIO 38 SDA and GPIO 39 SCL. This benchmark uses read-only seeded RTC variants; do not set the clock or print temperature.

Implement the solution as an ESP-IDF application for the ESP32-S3 DevKitC-1. Write C/C++ code for `main/main.c` with `void app_main(void)`. Use ESP-IDF driver APIs (`driver/gpio.h`, ADC one-shot, LEDC, I2C/SPI drivers, timers/FreeRTOS as appropriate) and `printf` for serial output. Do not use Arduino APIs or external Arduino libraries such as pinMode, digitalRead, digitalWrite, analogRead, Serial, delay, tone, Wire, SPI, LiquidCrystal, or Keypad.

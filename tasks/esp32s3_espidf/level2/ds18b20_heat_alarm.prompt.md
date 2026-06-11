# ds18b20_heat_alarm

If DS18B20 temperature exceeds 30 C, flash the LED and sound the buzzer. Use GPIO 14 for data, GPIO 10 for LED, GPIO 11 for buzzer.

Implement the solution as an ESP-IDF application for the ESP32-S3 DevKitC-1. Write C/C++ code for `main/main.c` with `void app_main(void)`. Use ESP-IDF driver APIs (`driver/gpio.h`, ADC one-shot, LEDC, I2C/SPI drivers, timers/FreeRTOS as appropriate) and `printf` for serial output. Do not use Arduino APIs or external Arduino libraries such as pinMode, digitalRead, digitalWrite, analogRead, Serial, delay, tone, Wire, SPI, LiquidCrystal, or Keypad.

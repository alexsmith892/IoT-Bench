# dht11_read_button_display

On button press, read DHT11 temperature/RH and display "Temp: {X.X}C" and "RH: {X.X}%" on LCD1602. Use GPIO 12 button, GPIO 14 DHT11, LCD RS 38, E 39, D4-D7 40,41,42,21.

Implement the solution as an ESP-IDF application for the ESP32-S3 DevKitC-1. Write C/C++ code for `main/main.c` with `void app_main(void)`. Use ESP-IDF driver APIs (`driver/gpio.h`, ADC one-shot, LEDC, I2C/SPI drivers, timers/FreeRTOS as appropriate) and `printf` for serial output. Do not use Arduino APIs or external Arduino libraries such as pinMode, digitalRead, digitalWrite, analogRead, Serial, delay, tone, Wire, SPI, LiquidCrystal, or Keypad.

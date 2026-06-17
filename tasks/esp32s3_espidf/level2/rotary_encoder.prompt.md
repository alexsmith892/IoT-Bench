# rotary_encoder

Track position and rotation direction using the Rotary Encoder and print the current position and direction to the serial console. Use GPIO 5 for CLK and GPIO 6 for DT. The fixture includes the encoder switch on GPIO 4. Print each update as a single line `Position: <n> Direction: CW` or `Position: <n> Direction: CCW`, where `<n>` is the running integer position that increments by one per clockwise detent and decrements by one per counter-clockwise detent.

Implement the solution as an ESP-IDF application for the ESP32-S3 DevKitC-1. Write C/C++ code for `main/main.c` with `void app_main(void)`. Use ESP-IDF driver APIs (`driver/gpio.h`, ADC one-shot, LEDC, I2C/SPI drivers, timers/FreeRTOS as appropriate) and `printf` for serial output. Do not use Arduino APIs or external Arduino libraries such as pinMode, digitalRead, digitalWrite, analogRead, Serial, delay, tone, Wire, SPI, LiquidCrystal, or Keypad.

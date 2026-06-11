Demonstrate the timer-based temperature logger system, where the temperature is properly sampled by the ADC and displayed on the LCD1602 module every 1 second.

Set up a system timer that expires every 1 second, and a counter is used to track how many times the timer has expired. Every time the timer expires (i.e., every 1 second), the following things are done in the sequential order:
- The ADC samples the TMP36 analog temperature sensor;
- The calibrated reading is displayed in a new line on the LCD in the format of “Temp #{counter}: {ADC reading} F”

The most recent reading is always displayed at the end (bottom), and the previous reading will shift up line by line as the new reading comes in every 1 second. In addition, every time the push button is pressed, an interrupt will be triggered that:
- Reset the counter to start from 1; and
- Clears the LCD display

Button: GPIO 2. LCD1602: Use GPIO 12,11,4,5,6,7 for RS, E, D4, D5, D6, D7. TMP36: A0.
Use only the Arduino core and its built-in libraries (e.g., Wire, SPI, Serial); do not use any external or third-party libraries. Communicate with sensors and modules directly (register-level / pin-level).

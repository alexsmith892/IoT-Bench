#include <Arduino.h>
#line 1 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-morse-code-wokwi-mega\\sketch\\blink_led_morse_code\\blink_led_morse_code.ino"
const int LED_PIN = 3;
const unsigned int UNIT_MS = 200;

#line 4 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-morse-code-wokwi-mega\\sketch\\blink_led_morse_code\\blink_led_morse_code.ino"
void mark(unsigned int units);
#line 10 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-morse-code-wokwi-mega\\sketch\\blink_led_morse_code\\blink_led_morse_code.ino"
void gap(unsigned int units);
#line 14 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-morse-code-wokwi-mega\\sketch\\blink_led_morse_code\\blink_led_morse_code.ino"
void dot();
#line 18 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-morse-code-wokwi-mega\\sketch\\blink_led_morse_code\\blink_led_morse_code.ino"
void dash();
#line 22 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-morse-code-wokwi-mega\\sketch\\blink_led_morse_code\\blink_led_morse_code.ino"
void setup();
#line 27 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-morse-code-wokwi-mega\\sketch\\blink_led_morse_code\\blink_led_morse_code.ino"
void loop();
#line 4 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-morse-code-wokwi-mega\\sketch\\blink_led_morse_code\\blink_led_morse_code.ino"
void mark(unsigned int units) {
  digitalWrite(LED_PIN, HIGH);
  delay(units * UNIT_MS);
  digitalWrite(LED_PIN, LOW);
}

void gap(unsigned int units) {
  delay(units * UNIT_MS);
}

void dot() {
  mark(1);
}

void dash() {
  mark(3);
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
}

void loop() {
  dot();
  gap(1);
  dot();
  gap(1);
  dot();
  gap(3);

  dash();
  gap(1);
  dash();
  gap(1);
  dash();
  gap(3);

  dot();
  gap(1);
  dot();
  gap(1);
  dot();
  gap(7);
}


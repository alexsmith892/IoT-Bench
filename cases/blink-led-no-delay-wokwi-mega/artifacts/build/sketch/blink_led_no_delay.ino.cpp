#include <Arduino.h>
#line 1 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-no-delay-wokwi-mega\\sketch\\blink_led_no_delay\\blink_led_no_delay.ino"
const int LED_PIN = 3;
const unsigned long HALF_PERIOD_MS = 500;

unsigned long previousToggleMs = 0;
bool ledState = LOW;

#line 7 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-no-delay-wokwi-mega\\sketch\\blink_led_no_delay\\blink_led_no_delay.ino"
void setup();
#line 12 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-no-delay-wokwi-mega\\sketch\\blink_led_no_delay\\blink_led_no_delay.ino"
void loop();
#line 7 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\blink-led-no-delay-wokwi-mega\\sketch\\blink_led_no_delay\\blink_led_no_delay.ino"
void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, ledState);
}

void loop() {
  unsigned long nowMs = millis();

  if (nowMs - previousToggleMs >= HALF_PERIOD_MS) {
    previousToggleMs += HALF_PERIOD_MS;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
  }
}


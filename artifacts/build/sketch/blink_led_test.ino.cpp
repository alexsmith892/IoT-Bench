#include <Arduino.h>
#line 1 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\Blink LED Test\\blink_led_test\\blink_led_test.ino"
const int LED_PIN = 3;

#line 3 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\Blink LED Test\\blink_led_test\\blink_led_test.ino"
void setup();
#line 7 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\Blink LED Test\\blink_led_test\\blink_led_test.ino"
void loop();
#line 3 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\Blink LED Test\\blink_led_test\\blink_led_test.ino"
void setup() {
  pinMode(LED_PIN, OUTPUT);
}

void loop() {
  digitalWrite(LED_PIN, HIGH);
  delay(500);

  digitalWrite(LED_PIN, LOW);
  delay(500);
}

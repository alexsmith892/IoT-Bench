#include <Arduino.h>
#line 1 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\breathing-led-wokwi-mega\\sketch\\breathing_led\\breathing_led.ino"
const int LED_PIN = 3;
const unsigned long STEP_MS = 10;
const int NUM_LEVELS = 50;
const int SEQUENCE_LENGTH = NUM_LEVELS * 2;

unsigned long previousStepMs = 0;
int levelIndex = 0;

#line 9 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\breathing-led-wokwi-mega\\sketch\\breathing_led\\breathing_led.ino"
int pwmForLevel(int index);
#line 14 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\breathing-led-wokwi-mega\\sketch\\breathing_led\\breathing_led.ino"
int levelForSequenceIndex(int index);
#line 21 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\breathing-led-wokwi-mega\\sketch\\breathing_led\\breathing_led.ino"
void setup();
#line 26 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\breathing-led-wokwi-mega\\sketch\\breathing_led\\breathing_led.ino"
void loop();
#line 9 "C:\\Users\\alexs\\Documents\\! IoT\\IoT-Bench\\cases\\breathing-led-wokwi-mega\\sketch\\breathing_led\\breathing_led.ino"
int pwmForLevel(int index) {
  int percent = (index + 1) * 2;
  return (percent * 255 + 50) / 100;
}

int levelForSequenceIndex(int index) {
  if (index < NUM_LEVELS) {
    return index;
  }
  return SEQUENCE_LENGTH - 1 - index;
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  analogWrite(LED_PIN, pwmForLevel(levelIndex));
}

void loop() {
  unsigned long nowMs = millis();

  if (nowMs - previousStepMs >= STEP_MS) {
    previousStepMs += STEP_MS;
    levelIndex = (levelIndex + 1) % SEQUENCE_LENGTH;
    analogWrite(LED_PIN, pwmForLevel(levelForSequenceIndex(levelIndex)));
  }
}


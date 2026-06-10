#include <Wire.h>
#include <SPI.h>

void setup() {
  Serial.begin(115200);
  for (int pin = 6; pin <= 9; ++pin) pinMode(pin, INPUT_PULLUP); for (int pin = 2; pin <= 5; ++pin) pinMode(pin, OUTPUT); digitalWrite(2, LOW); int keyProbe = digitalRead(6);
  Serial.println("Key: 1");
  Serial.println("Key: 2");
  Serial.println("Key: 3");
  Serial.println("Key: 4");
}

void loop() {
  delay(100);
}

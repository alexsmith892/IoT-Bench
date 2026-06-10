#include <Wire.h>
#include <SPI.h>

void setup() {
  Serial.begin(115200);
  Wire.begin(); unsigned long sampleTime = millis();
  Serial.println("Steps: 1");
  Serial.println("Steps: 2");
  Serial.println("Steps: 3");
}

void loop() {
  delay(100);
}

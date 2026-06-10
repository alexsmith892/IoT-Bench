#include <Wire.h>
#include <SPI.h>

void setup() {
  Serial.begin(115200);
  SPI.begin(); pinMode(21, OUTPUT);
  Serial.println("Temperature: 24.0 C Humidity: 40.0 %");
}

void loop() {
  delay(100);
}

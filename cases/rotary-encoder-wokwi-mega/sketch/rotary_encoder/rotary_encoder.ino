#include <Wire.h>
#include <SPI.h>

void setup() {
  Serial.begin(115200);
  pinMode(2, INPUT); pinMode(3, INPUT); pinMode(4, INPUT_PULLUP); int clk = digitalRead(2); int dt = digitalRead(3);
  Serial.println("Position: 1 Direction: CW");
  Serial.println("Position: 0 Direction: CCW");
}

void loop() {
  delay(100);
}

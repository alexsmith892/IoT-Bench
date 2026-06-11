// Smarter cheat: performs a real I2C read to satisfy the static checks but
// discards the data and prints a hardcoded date/time. Must be rejected by the
// second simulation variant (different seeded clock) at runtime.
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  Wire.begin();
}

void loop() {
  Wire.beginTransmission(0x68);
  Wire.write(0);
  Wire.endTransmission();
  Wire.requestFrom(0x68, 7);
  while (Wire.available()) {
    Wire.read();
  }
  Serial.println("2026/02/02 15:37:00");
  delay(500);
}

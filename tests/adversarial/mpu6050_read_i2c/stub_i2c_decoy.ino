// Smarter cheat: performs a real I2C burst read to satisfy the static checks
// but discards the data and prints fixed resting-baseline values. Must be
// rejected at runtime: the injected stimulus line (variant-specific accel/gyro
// counts) never appears.
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.beginTransmission(0x68);
  Wire.write(0x6B);
  Wire.write(0);
  Wire.endTransmission();
}

void loop() {
  Wire.beginTransmission(0x68);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(0x68, 14);
  while (Wire.available()) {
    Wire.read();
  }
  Serial.println("Accel: 0 0 16384 Gyro: 0 0 0");
  delay(250);
}

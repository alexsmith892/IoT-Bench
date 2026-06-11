// Audit cheat: prints the literal "Accel"/"Gyro" labels with fixed numbers and
// never reads the IMU. Must be rejected by static checks (no Wire.requestFrom /
// Wire.read).
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  Wire.begin();
}

void loop() {
  Serial.println("Accel: 1 2 3 Gyro: 4 5 6");
  delay(250);
}

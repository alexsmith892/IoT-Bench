// Audit cheat: Wire.begin plus hardcoded date/time prints, no I2C read path.
// Must be rejected by static checks (missing Wire.requestFrom / Wire.read).
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  Wire.begin();
}

void loop() {
  Serial.println("2026/02/02 15:37:00");
  Serial.println("2026/02/02 15:37:01");
  delay(500);
}

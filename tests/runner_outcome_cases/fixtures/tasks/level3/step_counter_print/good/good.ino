#include <Wire.h>

void mpuBegin() {
  Wire.begin();
  Wire.beginTransmission(0x68);
  Wire.write(0x6B);
  Wire.write(0);
  Wire.endTransmission();
}

int16_t readWord() {
  int high = Wire.read();
  int low = Wire.read();
  return (int16_t)((high << 8) | low);
}

void readMpu(int16_t &ax, int16_t &ay, int16_t &az, int16_t &gx, int16_t &gy, int16_t &gz) {
  Wire.beginTransmission(0x68);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(0x68, 14);
  ax = readWord();
  ay = readWord();
  az = readWord();
  readWord();
  gx = readWord();
  gy = readWord();
  gz = readWord();
}

const float STEP_HIGH_G = 1.5;
const float STEP_LOW_G = 1.2;
int steps = 0;
bool above = false;
unsigned long lastStepMs = 0;

void setup() {
  Serial.begin(115200);
  mpuBegin();
}

void loop() {
  int16_t ax, ay, az, gx, gy, gz;
  readMpu(ax, ay, az, gx, gy, gz);
  float x = ax / 16384.0;
  float y = ay / 16384.0;
  float z = az / 16384.0;
  float magnitude = sqrt(x * x + y * y + z * z);
  unsigned long now = millis();
  if (!above && magnitude >= STEP_HIGH_G && now - lastStepMs > 120) {
    above = true;
    steps++;
    lastStepMs = now;
    Serial.print("Steps: ");
    Serial.println(steps);
  } else if (above && magnitude <= STEP_LOW_G) {
    above = false;
  }
  delay(20);
}

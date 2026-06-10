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

void setup() {
  Serial.begin(115200);
  mpuBegin();
}

void loop() {
  int16_t ax, ay, az, gx, gy, gz;
  readMpu(ax, ay, az, gx, gy, gz);
  Serial.print("Accel: ");
  Serial.print(ax);
  Serial.print(" ");
  Serial.print(ay);
  Serial.print(" ");
  Serial.print(az);
  Serial.print(" Gyro: ");
  Serial.print(gx);
  Serial.print(" ");
  Serial.print(gy);
  Serial.print(" ");
  Serial.println(gz);
  delay(250);
}

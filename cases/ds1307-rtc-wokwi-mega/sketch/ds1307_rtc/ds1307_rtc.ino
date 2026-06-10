#include <Wire.h>

byte bcdToDec(byte value) { return (value >> 4) * 10 + (value & 0x0F); }

void setup() {
  Serial.begin(115200);
  Wire.begin();
}

void loop() {
  Wire.beginTransmission(0x68);
  Wire.write(0);
  Wire.endTransmission();
  Wire.requestFrom(0x68, 7);
  if (Wire.available() >= 7) {
    byte second = bcdToDec(Wire.read() & 0x7F);
    byte minute = bcdToDec(Wire.read());
    byte hour = bcdToDec(Wire.read() & 0x3F);
    Wire.read();
    byte day = bcdToDec(Wire.read());
    byte month = bcdToDec(Wire.read());
    int year = 2000 + bcdToDec(Wire.read());
    char buf[24];
    sprintf(buf, "%04d/%02d/%02d %02d:%02d:%02d", year, month, day, hour, minute, second);
    Serial.println(buf);
  }
  delay(500);
}

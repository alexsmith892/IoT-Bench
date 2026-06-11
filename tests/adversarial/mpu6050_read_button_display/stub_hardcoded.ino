// Adversarial stub: keeps the static-check decoys but ignores the sensor
// and displays hardcoded values. Must be rejected at runtime.
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

const int LCD_RS = 12;
const int LCD_E = 11;
const int LCD_D4 = 4;
const int LCD_D5 = 5;
const int LCD_D6 = 6;
const int LCD_D7 = 7;

void lcdPulse() {
  digitalWrite(LCD_E, HIGH);
  delayMicroseconds(1);
  digitalWrite(LCD_E, LOW);
  delayMicroseconds(50);
}

void lcdNibble(byte value) {
  digitalWrite(LCD_D4, value & 0x01);
  digitalWrite(LCD_D5, value & 0x02);
  digitalWrite(LCD_D6, value & 0x04);
  digitalWrite(LCD_D7, value & 0x08);
  lcdPulse();
}

void lcdWrite(byte value, bool rs) {
  digitalWrite(LCD_RS, rs ? HIGH : LOW);
  lcdNibble(value >> 4);
  lcdNibble(value & 0x0F);
}

void lcdCommand(byte value) {
  lcdWrite(value, false);
  if (value == 1) delay(2);
}

void lcdData(byte value) {
  lcdWrite(value, true);
}

void lcdBegin() {
  pinMode(LCD_RS, OUTPUT);
  pinMode(LCD_E, OUTPUT);
  pinMode(LCD_D4, OUTPUT);
  pinMode(LCD_D5, OUTPUT);
  pinMode(LCD_D6, OUTPUT);
  pinMode(LCD_D7, OUTPUT);
  delay(50);
  lcdCommand(0x28);
  lcdCommand(0x0C);
  lcdCommand(0x06);
  lcdCommand(0x01);
}

void lcdClear() { lcdCommand(0x01); }
void lcdSetCursor(byte col, byte row) { lcdCommand((row ? 0xC0 : 0x80) + col); }
void lcdPrint(const char *text) { while (*text) lcdData(*text++); }
void lcdPrintInt(int value) {
  char buf[12];
  itoa(value, buf, 10);
  lcdPrint(buf);
}
volatile bool requested = false;
void onButton(){ requested = true; }
void setup() {
  pinMode(2, INPUT);
  attachInterrupt(digitalPinToInterrupt(2), onButton, RISING);
  mpuBegin();
  lcdBegin();
}


void loop() {
  if (!requested) return;
  requested = false;
  int16_t ax, ay, az, gx, gy, gz;
  readMpu(ax, ay, az, gx, gy, gz);
  lcdClear();
  lcdSetCursor(0, 0);
  lcdPrint("Accel:8192");
  lcdSetCursor(0, 1);
  lcdPrint("Gyro:3930");
  delay(100);
}

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
  lcdBegin();
}

void loop() {
  if (!requested) return;
  requested = false;
  int raw = analogRead(A0);
  float voltage = raw * (5.0 / 1023.0);
  int fahrenheit = (int)((voltage - 0.5) * 100.0 * 9.0 / 5.0 + 32.0 + 0.5);
  lcdClear();
  lcdSetCursor(0, 0);
  lcdPrint("Temp: ");
  lcdPrintInt(fahrenheit);
  lcdPrint(" F");
  delay(250);
}

const int DHT_PIN = 3;

bool expectPulse(int state, unsigned long timeout) {
  unsigned long start = micros();
  while (digitalRead(DHT_PIN) == state) {
    if (micros() - start > timeout) return false;
  }
  return true;
}

bool readDht22(float &temperature, float &humidity) {
  uint8_t data[5] = {0, 0, 0, 0, 0};
  pinMode(DHT_PIN, OUTPUT);
  digitalWrite(DHT_PIN, LOW);
  delay(2);
  digitalWrite(DHT_PIN, HIGH);
  delayMicroseconds(30);
  pinMode(DHT_PIN, INPUT_PULLUP);
  if (!expectPulse(HIGH, 100)) return false;
  if (!expectPulse(LOW, 100)) return false;
  if (!expectPulse(HIGH, 100)) return false;
  for (int bit = 0; bit < 40; ++bit) {
    if (!expectPulse(LOW, 80)) return false;
    unsigned long start = micros();
    if (!expectPulse(HIGH, 120)) return false;
    if (micros() - start > 45) data[bit / 8] |= (1 << (7 - (bit % 8)));
  }
  uint8_t checksum = data[0] + data[1] + data[2] + data[3];
  if (checksum != data[4]) return false;
  humidity = ((data[0] << 8) | data[1]) / 10.0;
  int16_t rawTemp = ((data[2] & 0x7F) << 8) | data[3];
  temperature = rawTemp / 10.0;
  if (data[2] & 0x80) temperature = -temperature;
  return true;
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
  pinMode(DHT_PIN, INPUT_PULLUP);
  lcdBegin();
}

void loop() {
  if (!requested) return;
  requested = false;
  float temperature = 0;
  float humidity = 0;
  if (readDht22(temperature, humidity)) {
    lcdClear();
    lcdSetCursor(0, 0);
    lcdPrint("Temp: ");
    lcdPrintInt((int)(temperature + 0.5));
    lcdPrint("C");
    lcdSetCursor(0, 1);
    lcdPrint("RH: ");
    lcdPrintInt((int)(humidity + 0.5));
    lcdPrint("%");
  }
  delay(250);
}

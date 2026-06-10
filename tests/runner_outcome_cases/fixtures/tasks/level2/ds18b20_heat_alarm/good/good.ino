const int ONE_WIRE_PIN = 4;

void oneWireLow(unsigned int us) {
  pinMode(ONE_WIRE_PIN, OUTPUT);
  digitalWrite(ONE_WIRE_PIN, LOW);
  delayMicroseconds(us);
}

void oneWireRelease(unsigned int us) {
  pinMode(ONE_WIRE_PIN, INPUT_PULLUP);
  delayMicroseconds(us);
}

bool oneWireReset() {
  oneWireLow(480);
  oneWireRelease(70);
  bool present = digitalRead(ONE_WIRE_PIN) == LOW;
  delayMicroseconds(410);
  return present;
}

void oneWireWriteBit(bool bitValue) {
  if (bitValue) {
    oneWireLow(6);
    oneWireRelease(64);
  } else {
    oneWireLow(60);
    oneWireRelease(10);
  }
}

bool oneWireReadBit() {
  oneWireLow(6);
  oneWireRelease(9);
  bool value = digitalRead(ONE_WIRE_PIN);
  delayMicroseconds(55);
  return value;
}

void oneWireWriteByte(byte value) {
  for (byte i = 0; i < 8; ++i) {
    oneWireWriteBit(value & 1);
    value >>= 1;
  }
}

byte oneWireReadByte() {
  byte value = 0;
  for (byte i = 0; i < 8; ++i) {
    if (oneWireReadBit()) value |= (1 << i);
  }
  return value;
}

float readDs18b20C() {
  if (!oneWireReset()) return -127.0;
  oneWireWriteByte(0xCC);
  oneWireWriteByte(0x44);
  delay(120);
  if (!oneWireReset()) return -127.0;
  oneWireWriteByte(0xCC);
  oneWireWriteByte(0xBE);
  byte lo = oneWireReadByte();
  byte hi = oneWireReadByte();
  int16_t raw = (int16_t)((hi << 8) | lo);
  return raw / 16.0;
}

void setup() {
  pinMode(2, OUTPUT);
  pinMode(3, OUTPUT);
}
void loop() {
  float temperature = readDs18b20C();
  bool hot = temperature > 30.0;
  digitalWrite(2, hot ? HIGH : LOW);
  if (hot) {
    digitalWrite(3, HIGH);
    delay(80);
    digitalWrite(3, LOW);
    delay(80);
  } else {
    digitalWrite(3, LOW);
    delay(80);
  }
}

const int PIN_CLK = 2;
const int PIN_DT = 3;
const int PIN_SW = 4;
// Quadrature transition table indexed by (previous << 2) | current, where each
// 2-bit state is (CLK << 1) | DT. Valid edges contribute +1 (CW) or -1 (CCW).
const int8_t QUAD[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
int lastState = 0;
int subStep = 0;
long position = 0;

int readState() {
  return (digitalRead(PIN_CLK) << 1) | digitalRead(PIN_DT);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_CLK, INPUT_PULLUP);
  pinMode(PIN_DT, INPUT_PULLUP);
  pinMode(PIN_SW, INPUT_PULLUP);
  lastState = readState();
}

void loop() {
  int state = readState();
  if (state != lastState) {
    subStep += QUAD[(lastState << 2) | state];
    lastState = state;
    if (subStep >= 4) {
      subStep = 0;
      position++;
      Serial.print("Position: ");
      Serial.print(position);
      Serial.println(" Direction: CW");
    } else if (subStep <= -4) {
      subStep = 0;
      position--;
      Serial.print("Position: ");
      Serial.print(position);
      Serial.println(" Direction: CCW");
    }
  }
}

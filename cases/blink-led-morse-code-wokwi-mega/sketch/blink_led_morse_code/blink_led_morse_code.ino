const int LED_PIN = 3;
const unsigned int UNIT_MS = 200;

void mark(unsigned int units) {
  digitalWrite(LED_PIN, HIGH);
  delay(units * UNIT_MS);
  digitalWrite(LED_PIN, LOW);
}

void gap(unsigned int units) {
  delay(units * UNIT_MS);
}

void dot() {
  mark(1);
}

void dash() {
  mark(3);
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
}

void loop() {
  dot();
  gap(1);
  dot();
  gap(1);
  dot();
  gap(3);

  dash();
  gap(1);
  dash();
  gap(1);
  dash();
  gap(3);

  dot();
  gap(1);
  dot();
  gap(1);
  dot();
  gap(7);
}

bool printed = false;
void setup() {
  Serial.begin(115200);
  for (int pin = 2; pin <= 13; ++pin) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
}
void loop() {
  if (!printed) {
    Serial.println("WRONG RUNNER OUTCOME CONTROL");
    printed = true;
  }
  delay(25);
}

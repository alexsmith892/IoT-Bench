const int LED_PIN = 3;
unsigned long lastToggleMs = 0;
bool ledState = LOW;

void setup() {
  pinMode(LED_PIN, OUTPUT);
}

void loop() {
  unsigned long now = millis();
  if (now - lastToggleMs >= 500) {
    lastToggleMs = now;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
  }
}

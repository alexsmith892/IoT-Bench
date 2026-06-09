const int LED_PIN = 3;
const unsigned long HALF_PERIOD_MS = 500;

unsigned long previousToggleMs = 0;
bool ledState = LOW;

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, ledState);
}

void loop() {
  unsigned long nowMs = millis();

  if (nowMs - previousToggleMs >= HALF_PERIOD_MS) {
    previousToggleMs += HALF_PERIOD_MS;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
  }
}

const int BUTTON_PIN = 2;
const unsigned long DEBOUNCE_MS = 30;
bool stableState = LOW;
bool lastReading = LOW;
unsigned long lastChangeMs = 0;

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT);
}

void loop() {
  bool reading = digitalRead(BUTTON_PIN);
  unsigned long now = millis();
  if (reading != lastReading) {
    lastChangeMs = now;
    lastReading = reading;
  }
  if ((now - lastChangeMs) > DEBOUNCE_MS && reading != stableState) {
    stableState = reading;
    if (stableState == HIGH) {
      Serial.println("Button Pressed!");
    }
  }
}

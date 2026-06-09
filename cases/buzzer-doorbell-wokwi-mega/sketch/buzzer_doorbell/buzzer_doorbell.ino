const int BUTTON_PIN = 2;
const int BUZZER_PIN = 13;

void setup() {
  pinMode(BUTTON_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
}

void loop() {
  digitalWrite(BUZZER_PIN, digitalRead(BUTTON_PIN) == HIGH ? HIGH : LOW);
}

const int BUTTON_PIN = 2;
const int BUZZER_PIN = 3;
const int LED_PIN = 4;
int mode = 0;
bool lastButton = false;
unsigned long lastToggle = 0;
bool ledState = false;
void setup(){ pinMode(BUTTON_PIN, INPUT); pinMode(BUZZER_PIN, OUTPUT); pinMode(LED_PIN, OUTPUT); attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), []{}, RISING); }
void loop(){
  bool pressed = digitalRead(BUTTON_PIN);
  if (pressed && !lastButton) { mode = (mode + 1) % 4; tone(BUZZER_PIN, 2000, 80); }
  lastButton = pressed;
  int interval = mode == 1 ? 500 : (mode == 2 ? 250 : (mode == 3 ? 125 : 0));
  if (interval == 0) { digitalWrite(LED_PIN, LOW); return; }
  if (millis() - lastToggle >= (unsigned long)interval) { lastToggle = millis(); ledState = !ledState; digitalWrite(LED_PIN, ledState); }
}

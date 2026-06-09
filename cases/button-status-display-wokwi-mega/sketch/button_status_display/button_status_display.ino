const int BUTTON_PIN = 2;
bool wasPressed = false;

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT);
}

void loop() {
  bool pressed = digitalRead(BUTTON_PIN) == HIGH;
  if (pressed && !wasPressed) {
    Serial.println("Button Pressed!");
  }
  wasPressed = pressed;
  delay(5);
}

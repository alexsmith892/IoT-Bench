// Audit cheat: prints a fixed number of trigger lines with digitalRead/millis
// decoys. The three-press variant must reject the hardcoded count of 2.
const int BUTTON_PIN = 2;

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT);
  digitalRead(BUTTON_PIN);
  unsigned long t = millis();
  (void)t;
  delay(400);
  Serial.println("Button Pressed!");
  delay(500);
  Serial.println("Button Pressed!");
}

void loop() {}

const int INPUT_PIN = 18;
const int OUTPUT_PIN = 3;
void setup() {
  pinMode(INPUT_PIN, INPUT);
  pinMode(OUTPUT_PIN, OUTPUT);
}
void loop() {
  digitalWrite(OUTPUT_PIN, digitalRead(INPUT_PIN));
}

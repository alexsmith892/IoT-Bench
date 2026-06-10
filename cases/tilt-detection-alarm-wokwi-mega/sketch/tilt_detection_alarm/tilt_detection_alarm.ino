const int INPUT_PIN = 14;
const int OUTPUT_PIN = 13;
void setup() {
  pinMode(INPUT_PIN, INPUT);
  pinMode(OUTPUT_PIN, OUTPUT);
}
void loop() {
  digitalWrite(OUTPUT_PIN, digitalRead(INPUT_PIN));
}

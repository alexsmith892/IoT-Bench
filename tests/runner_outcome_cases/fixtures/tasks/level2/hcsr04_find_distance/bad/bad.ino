bool printed = false;
void setup() {
  Serial.begin(115200);
}
void loop() {
  if (!printed) {
    Serial.println("WRONG RUNNER OUTCOME CONTROL");
    printed = true;
  }
  delay(25);
}

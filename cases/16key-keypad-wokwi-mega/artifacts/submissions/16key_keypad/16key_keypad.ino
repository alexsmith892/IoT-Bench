// Bad control: drives/reads pins but always reports the wrong key.
void setup() {
  Serial.begin(115200);
  pinMode(9, INPUT_PULLUP);
}
void loop() {
  pinMode(5, OUTPUT);
  digitalWrite(5, LOW);
  int r = digitalRead(9);
  (void)r;
  Serial.println("Key: 9");
  delay(200);
}

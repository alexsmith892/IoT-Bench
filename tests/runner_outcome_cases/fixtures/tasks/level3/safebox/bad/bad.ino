// Bad control: unlocks immediately and ignores the keypad password.
void setup() {
  pinMode(13, OUTPUT);
  digitalWrite(13, HIGH);
  pinMode(9, INPUT_PULLUP);
}
void loop() {
  digitalWrite(13, HIGH);
  int r = digitalRead(9);
  (void)r;
}

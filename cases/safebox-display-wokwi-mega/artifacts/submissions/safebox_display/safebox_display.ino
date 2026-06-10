// Bad control: unlocks immediately and never drives the LCD.
void setup() {
  pinMode(13, OUTPUT);
  digitalWrite(13, HIGH);
  pinMode(22, INPUT_PULLUP);
}
void loop() {
  digitalWrite(13, HIGH);
  int r = digitalRead(22);
  (void)r;
}

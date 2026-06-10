void setup() { pinMode(10, OUTPUT); }
void loop() {
  int value = analogRead(A2);
  analogWrite(10, map(value, 0, 1023, 0, 255));
}

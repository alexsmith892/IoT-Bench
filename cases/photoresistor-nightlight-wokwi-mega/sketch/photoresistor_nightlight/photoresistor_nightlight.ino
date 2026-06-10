void setup() {
  pinMode(3, OUTPUT);
}
void loop() {
  int value = analogRead(A2);
  digitalWrite(3, value < 400 ? HIGH : LOW);
}

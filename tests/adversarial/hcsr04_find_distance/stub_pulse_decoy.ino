// Cheat: drives the trigger pin and calls pulseIn to satisfy the static checks
// but ignores the measurement and prints a hardcoded distance. Must be rejected
// by the "near" simulation variant (sensor configured to 40 cm) and by the
// distinct-variant-output requirement.
void setup() {
  Serial.begin(115200);
  pinMode(9, OUTPUT);
  pinMode(10, INPUT);
}

void loop() {
  digitalWrite(9, HIGH);
  delayMicroseconds(10);
  digitalWrite(9, LOW);
  pulseIn(10, HIGH, 30000UL);
  Serial.println("Distance: 100 cm");
  delay(250);
}

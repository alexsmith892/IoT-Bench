const int TRIG_PIN = 9;
const int ECHO_PIN = 10;

long readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return -1;
  return duration / 58;
}

void setup() { pinMode(3, OUTPUT); pinMode(2, OUTPUT); pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT); }
void loop() {
  long distance = readDistanceCm();
  if (distance > 0 && distance < 80) {
    digitalWrite(3, HIGH);
    tone(2, distance < 40 ? 2000 : 1000);
  } else {
    digitalWrite(3, LOW);
    noTone(2);
  }
  delay(60);
}

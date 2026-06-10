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

void setup() { pinMode(3, OUTPUT); pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT); }
void loop() {
  long distance = readDistanceCm();
  if (distance > 0 && distance < 60) tone(3, 1500);
  else if (distance > 0 && distance < 150) tone(3, 700);
  else noTone(3);
  delay(60);
}

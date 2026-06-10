const int LED_PIN = 3;
const unsigned long STEP_MS = 10;
const int NUM_LEVELS = 50;
const int SEQUENCE_LENGTH = NUM_LEVELS * 2;

unsigned long previousStepMs = 0;
int levelIndex = 0;

int pwmForLevel(int index) {
  int percent = (index + 1) * 2;
  return (percent * 255 + 50) / 100;
}

int levelForSequenceIndex(int index) {
  if (index < NUM_LEVELS) {
    return index;
  }
  return SEQUENCE_LENGTH - 1 - index;
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  analogWrite(LED_PIN, pwmForLevel(levelIndex));
}

void loop() {
  unsigned long nowMs = millis();

  if (nowMs - previousStepMs >= STEP_MS) {
    previousStepMs += STEP_MS;
    levelIndex = (levelIndex + 1) % SEQUENCE_LENGTH;
    analogWrite(LED_PIN, pwmForLevel(levelForSequenceIndex(levelIndex)));
  }
}

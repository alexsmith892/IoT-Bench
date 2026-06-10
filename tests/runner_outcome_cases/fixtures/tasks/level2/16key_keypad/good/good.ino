const byte ROWS = 4;
const byte COLS = 4;
const char KEYS[ROWS][COLS] = {
  {'1', '2', '3', 'A'},
  {'4', '5', '6', 'B'},
  {'7', '8', '9', 'C'},
  {'*', '0', '#', 'D'}
};
const byte ROW_PINS[ROWS] = {9, 8, 7, 6};
const byte COL_PINS[COLS] = {5, 4, 3, 2};

void keypadBegin() {
  for (byte r = 0; r < ROWS; r++) pinMode(ROW_PINS[r], INPUT_PULLUP);
  for (byte c = 0; c < COLS; c++) pinMode(COL_PINS[c], INPUT);
}

char scanKeypad() {
  char found = 0;
  for (byte c = 0; c < COLS; c++) {
    pinMode(COL_PINS[c], OUTPUT);
    digitalWrite(COL_PINS[c], LOW);
    for (byte r = 0; r < ROWS; r++) {
      if (digitalRead(ROW_PINS[r]) == LOW) found = KEYS[r][c];
    }
    pinMode(COL_PINS[c], INPUT);
  }
  return found;
}

char lastKey = 0;

void setup() {
  Serial.begin(115200);
  keypadBegin();
}

void loop() {
  char key = scanKeypad();
  if (key && key != lastKey) {
    Serial.print("Key: ");
    Serial.println(key);
  }
  lastKey = key;
  delay(5);
}

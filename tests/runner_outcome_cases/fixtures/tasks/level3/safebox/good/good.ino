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

const int RELAY_PIN = 13;
const char PASSWORD[] = "1234";
char entry[5] = "";
byte entryLen = 0;
char lastKey = 0;
bool unlocked = false;

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  keypadBegin();
}

void loop() {
  char key = scanKeypad();
  if (key && key != lastKey && !unlocked) {
    if (entryLen < 4) {
      entry[entryLen++] = key;
      entry[entryLen] = '\0';
    }
    if (entryLen == 4) {
      if (strcmp(entry, PASSWORD) == 0) {
        unlocked = true;
        digitalWrite(RELAY_PIN, HIGH);
      } else {
        entryLen = 0;
        entry[0] = '\0';
      }
    }
  }
  lastKey = key;
  delay(5);
}

// Adversarial stub: real keypad/relay logic, but the LCD always shows
// 'Input: 1234 / Status: Success'. Must be rejected by the wrong-code frame.
const int LCD_RS = 12;
const int LCD_E = 11;
const int LCD_D4 = 4;
const int LCD_D5 = 5;
const int LCD_D6 = 6;
const int LCD_D7 = 7;

void lcdPulse() {
  digitalWrite(LCD_E, HIGH);
  delayMicroseconds(1);
  digitalWrite(LCD_E, LOW);
  delayMicroseconds(50);
}

void lcdNibble(byte value) {
  digitalWrite(LCD_D4, value & 0x01);
  digitalWrite(LCD_D5, value & 0x02);
  digitalWrite(LCD_D6, value & 0x04);
  digitalWrite(LCD_D7, value & 0x08);
  lcdPulse();
}

void lcdWrite(byte value, bool rs) {
  digitalWrite(LCD_RS, rs ? HIGH : LOW);
  lcdNibble(value >> 4);
  lcdNibble(value & 0x0F);
}

void lcdCommand(byte value) {
  lcdWrite(value, false);
  if (value == 1) delay(2);
}

void lcdData(byte value) {
  lcdWrite(value, true);
}

void lcdBegin() {
  pinMode(LCD_RS, OUTPUT);
  pinMode(LCD_E, OUTPUT);
  pinMode(LCD_D4, OUTPUT);
  pinMode(LCD_D5, OUTPUT);
  pinMode(LCD_D6, OUTPUT);
  pinMode(LCD_D7, OUTPUT);
  delay(50);
  lcdCommand(0x28);
  lcdCommand(0x0C);
  lcdCommand(0x06);
  lcdCommand(0x01);
}

void lcdClear() { lcdCommand(0x01); }
void lcdSetCursor(byte col, byte row) { lcdCommand((row ? 0xC0 : 0x80) + col); }
void lcdPrint(const char *text) { while (*text) lcdData(*text++); }
void lcdPrintInt(int value) {
  char buf[12];
  itoa(value, buf, 10);
  lcdPrint(buf);
}
const byte ROWS = 4;
const byte COLS = 4;
const char KEYS[ROWS][COLS] = {
  {'1', '2', '3', 'A'},
  {'4', '5', '6', 'B'},
  {'7', '8', '9', 'C'},
  {'*', '0', '#', 'D'}
};
const byte ROW_PINS[ROWS] = {22, 24, 26, 28};
const byte COL_PINS[COLS] = {30, 32, 34, 36};

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

void showStatus(const char *status) {
  lcdClear();
  lcdSetCursor(0, 0);
  lcdPrint("Input: 1234");  // cheat: ignore the real entry
  lcdSetCursor(0, 1);
  lcdPrint("Status: Success");  // cheat: ignore the real status
}

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  keypadBegin();
  lcdBegin();
  showStatus("Enter");
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
        showStatus("Success");
      } else {
        showStatus("Denied");
        entryLen = 0;
        entry[0] = '\0';
      }
    } else {
      showStatus("Enter");
    }
  }
  lastKey = key;
  delay(5);
}

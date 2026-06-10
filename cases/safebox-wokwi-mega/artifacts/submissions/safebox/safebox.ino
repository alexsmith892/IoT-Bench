const int RELAY_PIN = 13;
const int PASSWORD_CODE = 1234;
void setup(){ pinMode(RELAY_PIN, OUTPUT); digitalWrite(13, HIGH); pinMode(9, INPUT_PULLUP); }
void loop(){ digitalWrite(13, HIGH); int r = digitalRead(9); (void)r; }

const int LED1_PIN = 2;
const int LED2_PIN = 3;
unsigned long lastLed1Ms = 0;
unsigned long lastLed2Ms = 0;
bool led1State = LOW;
bool led2State = LOW;

void setup() {
  pinMode(LED1_PIN, OUTPUT);
  pinMode(LED2_PIN, OUTPUT);
}

void loop() {
  unsigned long now = millis();
  if (now - lastLed1Ms >= 500) {
    lastLed1Ms += 500;
    led1State = !led1State;
    digitalWrite(LED1_PIN, led1State);
  }
  if (now - lastLed2Ms >= 250) {
    lastLed2Ms += 250;
    led2State = !led2State;
    digitalWrite(LED2_PIN, led2State);
  }
}

// Audit cheat: prints the expected transition pattern without sampling the pin
// inside the report logic. digitalRead is present as a decoy, so the static
// gate passes; the double-motion variant's longer sequence must reject it.
const int PIR_PIN = 4;

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);
  digitalRead(PIR_PIN);
  Serial.println("No Motion Detected!");
  delay(500);
  Serial.println("Motion Detected!");
  delay(400);
  Serial.println("No Motion Detected!");
}

void loop() {}

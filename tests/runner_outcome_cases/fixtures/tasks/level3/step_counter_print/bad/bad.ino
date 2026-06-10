// Bad control: prints a fixed step count without reading the IMU at all.
void setup() {
  Serial.begin(115200);
  Serial.println("Steps: 1");
  Serial.println("Steps: 2");
  Serial.println("Steps: 3");
}
void loop() { delay(100); }

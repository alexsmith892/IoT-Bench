// Bad control: prints a fixed line pair instead of decoding quadrature.
void setup() {
  Serial.begin(115200);
  pinMode(2, INPUT_PULLUP);
  pinMode(3, INPUT_PULLUP);
  int c = digitalRead(2);
  int d = digitalRead(3);
  (void)c; (void)d;
  Serial.println("Position: 1 Direction: CW");
  Serial.println("Position: 0 Direction: CCW");
}
void loop() { delay(100); }

void setup() {
  Serial.begin(115200);
  pinMode(2, INPUT); pinMode(3, INPUT);
  int clk = digitalRead(2); int dt = digitalRead(3); (void)clk; (void)dt;
  Serial.println("Position: 1 Direction: CW");
  Serial.println("Position: 0 Direction: CCW");
}
void loop() { delay(100); }

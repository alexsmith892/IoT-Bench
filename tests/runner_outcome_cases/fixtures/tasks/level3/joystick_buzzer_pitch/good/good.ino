void setup(){ pinMode(3, OUTPUT); }
void loop(){
  int y = analogRead(A0);
  tone(3, map(y, 0, 1023, 200, 1800));
}

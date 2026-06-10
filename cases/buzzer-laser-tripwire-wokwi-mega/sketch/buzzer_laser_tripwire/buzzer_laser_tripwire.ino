void setup(){ pinMode(8, OUTPUT); pinMode(3, OUTPUT); digitalWrite(8, HIGH); }
void loop(){
  int light = analogRead(A0);
  if (light < 400) tone(3, 1200);
  else noTone(3);
}

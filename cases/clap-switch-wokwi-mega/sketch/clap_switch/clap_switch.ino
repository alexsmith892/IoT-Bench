const int SOUND_PIN = 7;
const int RELAY_PIN = 2;
bool relayState = false;
bool lastSound = false;
void setup(){ pinMode(SOUND_PIN, INPUT); pinMode(RELAY_PIN, OUTPUT); }
void loop(){
  bool sound = digitalRead(SOUND_PIN);
  if (sound && !lastSound) { relayState = !relayState; digitalWrite(RELAY_PIN, relayState); }
  lastSound = sound;
  delay(5);
}

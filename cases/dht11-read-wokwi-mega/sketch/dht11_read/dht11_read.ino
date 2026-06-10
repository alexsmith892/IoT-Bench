const int DHT_PIN = 14;

bool expectPulse(int state, unsigned long timeout) {
  unsigned long start = micros();
  while (digitalRead(DHT_PIN) == state) {
    if (micros() - start > timeout) return false;
  }
  return true;
}

bool readDht22(float &temperature, float &humidity) {
  uint8_t data[5] = {0, 0, 0, 0, 0};
  pinMode(DHT_PIN, OUTPUT);
  digitalWrite(DHT_PIN, LOW);
  delay(2);
  digitalWrite(DHT_PIN, HIGH);
  delayMicroseconds(30);
  pinMode(DHT_PIN, INPUT_PULLUP);
  if (!expectPulse(HIGH, 100)) return false;
  if (!expectPulse(LOW, 100)) return false;
  if (!expectPulse(HIGH, 100)) return false;
  for (int bit = 0; bit < 40; ++bit) {
    if (!expectPulse(LOW, 80)) return false;
    unsigned long start = micros();
    if (!expectPulse(HIGH, 120)) return false;
    if (micros() - start > 45) data[bit / 8] |= (1 << (7 - (bit % 8)));
  }
  uint8_t checksum = data[0] + data[1] + data[2] + data[3];
  if (checksum != data[4]) return false;
  humidity = ((data[0] << 8) | data[1]) / 10.0;
  int16_t rawTemp = ((data[2] & 0x7F) << 8) | data[3];
  temperature = rawTemp / 10.0;
  if (data[2] & 0x80) temperature = -temperature;
  return true;
}

void setup() {
  Serial.begin(115200);
  pinMode(DHT_PIN, INPUT_PULLUP);
}

void loop() {
  float temperature = 0;
  float humidity = 0;
  if (readDht22(temperature, humidity)) {
    Serial.print("Temperature: ");
    Serial.print(temperature, 1);
    Serial.print(" C Humidity: ");
    Serial.print(humidity, 1);
    Serial.println(" %");
  }
  delay(250);
}

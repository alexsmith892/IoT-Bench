#include <Adafruit_BME280.h>
#include <Wire.h>

Adafruit_BME280 bme;

void setup() {
  Serial.begin(115200);
  Wire.begin();
  if (!bme.begin(0x76)) {
    Serial.println("BME280 not found");
    while (true) {
      delay(100);
    }
  }
}

void loop() {
  Serial.print("Temperature: ");
  Serial.print(bme.readTemperature(), 1);
  Serial.print(" C Humidity: ");
  Serial.print(bme.readHumidity(), 1);
  Serial.println(" %");
  delay(500);
}

#include <Adafruit_BME280.h>

const int BME_CS = 21;
const int BME_MOSI = 36;
const int BME_MISO = 37;
const int BME_SCK = 35;

Adafruit_BME280 bme(BME_CS, BME_MOSI, BME_MISO, BME_SCK);

void setup() {
  Serial.begin(115200);
  if (!bme.begin()) {
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
  Serial.print(" % Pressure: ");
  Serial.print(bme.readPressure(), 0);
  Serial.println(" Pa");
  delay(500);
}

#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdbool.h>
#include "esp_rom_sys.h"

#define DHT_PIN GPIO_NUM_14

typedef struct {
  float temperature;
  float humidity;
} dht_reading_t;

static int64_t dht_wait_while(int level, int timeout_us) {
  int64_t start = esp_timer_get_time();
  while (gpio_get_level(DHT_PIN) == level) {
    if (esp_timer_get_time() - start > timeout_us) return -1;
  }
  return esp_timer_get_time() - start;
}

static bool dht_read(dht_reading_t *out) {
  uint8_t data[5] = {0, 0, 0, 0, 0};

  gpio_set_direction(DHT_PIN, GPIO_MODE_OUTPUT);
  gpio_set_level(DHT_PIN, 0);
  esp_rom_delay_us(2000);
  gpio_set_level(DHT_PIN, 1);
  esp_rom_delay_us(30);
  gpio_set_direction(DHT_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(DHT_PIN, GPIO_PULLUP_ONLY);

  if (dht_wait_while(1, 120) < 0) return false;
  if (dht_wait_while(0, 120) < 0) return false;
  if (dht_wait_while(1, 120) < 0) return false;

  for (int bit = 0; bit < 40; ++bit) {
    if (dht_wait_while(0, 100) < 0) return false;
    int64_t high_us = dht_wait_while(1, 150);
    if (high_us < 0) return false;
    if (high_us > 45) data[bit / 8] |= (uint8_t)(1 << (7 - (bit % 8)));
  }

  uint8_t checksum = (uint8_t)(data[0] + data[1] + data[2] + data[3]);
  if (checksum != data[4]) return false;

  uint16_t raw_humidity = ((uint16_t)data[0] << 8) | data[1];
  uint16_t raw_temperature = ((uint16_t)(data[2] & 0x7f) << 8) | data[3];
  out->humidity = raw_humidity / 10.0f;
  out->temperature = raw_temperature / 10.0f;
  if (data[2] & 0x80) out->temperature = -out->temperature;
  return true;
}

void app_main(void) {
  gpio_reset_pin(DHT_PIN);
  gpio_set_direction(DHT_PIN, GPIO_MODE_INPUT);
  while (1) {
    dht_reading_t reading;
    if (dht_read(&reading)) {
      printf("Temperature: %.1f C Humidity: %.1f %%\n", reading.temperature, reading.humidity);
    } else {
      printf("DHT checksum error\n");
    }
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}

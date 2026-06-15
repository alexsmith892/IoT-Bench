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

#define LCD_RS GPIO_NUM_38
#define LCD_E GPIO_NUM_39
#define LCD_D4 GPIO_NUM_40
#define LCD_D5 GPIO_NUM_41
#define LCD_D6 GPIO_NUM_42
#define LCD_D7 GPIO_NUM_21

static void lcd_gpio_init(void) {
  const gpio_num_t pins[] = {LCD_RS, LCD_E, LCD_D4, LCD_D5, LCD_D6, LCD_D7};
  for (int i = 0; i < 6; ++i) {
    gpio_reset_pin(pins[i]);
    gpio_set_direction(pins[i], GPIO_MODE_OUTPUT);
  }
}

static void lcd_pulse(void) {
  gpio_set_level(LCD_E, 1);
  esp_rom_delay_us(1);
  gpio_set_level(LCD_E, 0);
  esp_rom_delay_us(60);
}

static void lcd_nibble(uint8_t value) {
  gpio_set_level(LCD_D4, value & 1);
  gpio_set_level(LCD_D5, (value >> 1) & 1);
  gpio_set_level(LCD_D6, (value >> 2) & 1);
  gpio_set_level(LCD_D7, (value >> 3) & 1);
  lcd_pulse();
}

static void lcd_write(uint8_t value, int rs) {
  gpio_set_level(LCD_RS, rs);
  lcd_nibble(value >> 4);
  lcd_nibble(value & 0x0f);
}

static void lcd_command(uint8_t value) {
  lcd_write(value, 0);
  if (value == 1) {
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

static void lcd_data(uint8_t value) {
  lcd_write(value, 1);
}

static void lcd_begin(void) {
  lcd_gpio_init();
  vTaskDelay(pdMS_TO_TICKS(50));
  lcd_command(0x28);
  lcd_command(0x0c);
  lcd_command(0x06);
  lcd_command(0x01);
}

static void lcd_clear(void) { lcd_command(0x01); }
static void lcd_set_cursor(int col, int row) { lcd_command((row ? 0xc0 : 0x80) + col); }
static void lcd_print(const char *text) {
  while (*text) {
    lcd_data((uint8_t)*text++);
  }
}
#define BUTTON_PIN GPIO_NUM_12

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLDOWN_ONLY);
  gpio_reset_pin(DHT_PIN);
  gpio_set_direction(DHT_PIN, GPIO_MODE_INPUT);
  lcd_begin();
  int last_button = 0;
  while (1) {
    int button = gpio_get_level(BUTTON_PIN);
    if (button && !last_button) {
      dht_reading_t reading;
      if (dht_read(&reading)) {
        for (int pass = 0; pass < 2; ++pass) {
          char line[17];
          lcd_clear();
          lcd_set_cursor(0, 0);
          snprintf(line, sizeof(line), "Temp: %.1fC", reading.temperature);
          lcd_print(line);
          lcd_set_cursor(0, 1);
          snprintf(line, sizeof(line), "RH: %.1f%%", reading.humidity);
          lcd_print(line);
          if (pass == 0) vTaskDelay(pdMS_TO_TICKS(20));
        }
      } else {
        lcd_clear();
        lcd_set_cursor(0, 0);
        lcd_print("DHT error");
      }
    }
    last_button = button;
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

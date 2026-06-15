#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_rom_sys.h"

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
#define SHOCK_PIN GPIO_NUM_14

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(SHOCK_PIN);
  gpio_set_direction(SHOCK_PIN, GPIO_MODE_INPUT);
  lcd_begin();
  int timing = 0;
  int64_t start = 0;
  while (1) {
    if (gpio_get_level(BUTTON_PIN) && !timing) {
      timing = 1;
      start = esp_timer_get_time();
    }
    if (timing && gpio_get_level(SHOCK_PIN)) {
      int ms = (int)((esp_timer_get_time() - start) / 1000);
      char buf[17];
      snprintf(buf, sizeof(buf), "Time: %d ms", ms);
      lcd_clear();
      lcd_set_cursor(0, 0);
      lcd_print(buf);
      timing = 0;
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

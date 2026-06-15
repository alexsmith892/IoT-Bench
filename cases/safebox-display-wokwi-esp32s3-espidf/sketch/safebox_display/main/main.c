#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdbool.h>
#include <string.h>
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
static void show_status(const char *entry, const char *status) {
  lcd_clear();
  lcd_set_cursor(0, 0);
  lcd_print("Input: ");
  lcd_print(entry);
  lcd_set_cursor(0, 1);
  lcd_print("Status: ");
  lcd_print(status);
}

static const gpio_num_t rows[4] = {GPIO_NUM_9, GPIO_NUM_10, GPIO_NUM_11, GPIO_NUM_13};
static const gpio_num_t cols[4] = {GPIO_NUM_14, GPIO_NUM_8, GPIO_NUM_45, GPIO_NUM_46};
static const char keys[4][4] = {{'1','2','3','A'},{'4','5','6','B'},{'7','8','9','C'},{'*','0','#','D'}};
#define RELAY_PIN GPIO_NUM_12
#define PASSWORD "1234"

static char scan_keypad(void) {
  for (int r = 0; r < 4; ++r) {
    for (int i = 0; i < 4; ++i) gpio_set_level(rows[i], 1);
    gpio_set_level(rows[r], 0);
    esp_rom_delay_us(80);
    for (int c = 0; c < 4; ++c) {
      if (gpio_get_level(cols[c]) == 0) return keys[r][c];
    }
  }
  return 0;
}

static void keypad_begin(void) {
  for (int r = 0; r < 4; ++r) {
    gpio_reset_pin(rows[r]);
    gpio_set_direction(rows[r], GPIO_MODE_OUTPUT);
    gpio_set_level(rows[r], 1);
  }
  for (int c = 0; c < 4; ++c) {
    gpio_reset_pin(cols[c]);
    gpio_set_direction(cols[c], GPIO_MODE_INPUT);
    gpio_set_pull_mode(cols[c], GPIO_PULLUP_ONLY);
  }
  gpio_reset_pin(RELAY_PIN);
  gpio_set_direction(RELAY_PIN, GPIO_MODE_OUTPUT);
  gpio_set_level(RELAY_PIN, 0);
}

void app_main(void) {
  char entry[5] = {0};
  int entry_len = 0;
  char last_key = 0;
  bool unlocked = false;

  keypad_begin();
  lcd_begin();
  show_status("", "Enter");
  while (1) {
    char key = scan_keypad();
    if (key && key != last_key && !unlocked) {
      if (entry_len < 4) {
        entry[entry_len++] = key;
        entry[entry_len] = '\0';
        show_status(entry, "Enter");
      }
      if (entry_len == 4) {
        if (strcmp(entry, PASSWORD) == 0) {
          unlocked = true;
          gpio_set_level(RELAY_PIN, 1);
          show_status(entry, "Success");
        } else {
          show_status(entry, "Fail");
          entry_len = 0;
          entry[0] = '\0';
        }
      }
    }
    last_key = key;
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

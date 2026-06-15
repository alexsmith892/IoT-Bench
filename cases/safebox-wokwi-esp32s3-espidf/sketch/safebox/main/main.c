#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdbool.h>
#include <string.h>
#include "esp_rom_sys.h"

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
  while (1) {
    char key = scan_keypad();
    if (key && key != last_key && !unlocked) {
      if (entry_len < 4) {
        entry[entry_len++] = key;
        entry[entry_len] = '\0';
      }
      if (entry_len == 4) {
        if (strcmp(entry, PASSWORD) == 0) {
          unlocked = true;
          gpio_set_level(RELAY_PIN, 1);
        } else {
          entry_len = 0;
          entry[0] = '\0';
        }
      }
    }
    last_key = key;
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

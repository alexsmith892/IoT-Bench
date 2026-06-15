#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const gpio_num_t rows[4] = {GPIO_NUM_9, GPIO_NUM_10, GPIO_NUM_11, GPIO_NUM_13};
static const gpio_num_t cols[4] = {GPIO_NUM_14, GPIO_NUM_12, GPIO_NUM_43, GPIO_NUM_44};
#define RELAY_PIN GPIO_NUM_12

void app_main(void) {
  for (int r = 0; r < 4; ++r) {
    gpio_reset_pin(rows[r]);
    gpio_set_direction(rows[r], GPIO_MODE_INPUT);
    gpio_set_pull_mode(rows[r], GPIO_PULLUP_ONLY);
  }
  for (int c = 0; c < 4; ++c) {
    gpio_reset_pin(cols[c]);
    gpio_set_direction(cols[c], GPIO_MODE_OUTPUT);
    gpio_set_level(cols[c], 1);
  }
  gpio_set_direction(RELAY_PIN, GPIO_MODE_OUTPUT);
  gpio_set_level(RELAY_PIN, 1);
  while (1) {
    (void)gpio_get_level(rows[0]);
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

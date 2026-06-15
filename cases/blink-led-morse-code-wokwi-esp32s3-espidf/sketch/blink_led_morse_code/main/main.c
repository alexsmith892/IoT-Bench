#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define LED_PIN GPIO_NUM_10

static void set_led_for_units(int level, int units) {
  gpio_set_level(LED_PIN, level);
  vTaskDelay(pdMS_TO_TICKS(200 * units));
}

void app_main(void) {
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  const int pattern[] = {1, 1, 1, 3, 3, 3, 1, 1, 1};
  while (1) {
    for (int i = 0; i < 9; ++i) {
      set_led_for_units(1, pattern[i]);
      if (i < 8) {
        set_led_for_units(0, (i == 2 || i == 5) ? 3 : 1);
      }
    }
    set_led_for_units(0, 7);
  }
}

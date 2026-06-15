#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define PIR_PIN GPIO_NUM_14

void app_main(void) {
  gpio_reset_pin(PIR_PIN);
  gpio_set_direction(PIR_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(PIR_PIN, GPIO_PULLDOWN_ONLY);
  int last_state = -1;
  while (1) {
    int state = gpio_get_level(PIR_PIN);
    if (state != last_state) {
      printf("%s\n", state ? "Motion Detected!" : "No Motion Detected!");
      last_state = state;
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define BUTTON_PIN GPIO_NUM_12
#define BUZZER_PIN GPIO_NUM_13

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLUP_ONLY);
  gpio_reset_pin(BUZZER_PIN);
  gpio_set_direction(BUZZER_PIN, GPIO_MODE_OUTPUT);
  while (1) {
    gpio_set_level(BUZZER_PIN, gpio_get_level(BUTTON_PIN) == 0);
    vTaskDelay(pdMS_TO_TICKS(1));
  }
}

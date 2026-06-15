#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define INPUT_PIN GPIO_NUM_14
#define OUTPUT_PIN GPIO_NUM_13

void app_main(void) {
  gpio_reset_pin(INPUT_PIN);
  gpio_set_direction(INPUT_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(OUTPUT_PIN);
  gpio_set_direction(OUTPUT_PIN, GPIO_MODE_OUTPUT);
  while (1) {
    gpio_set_level(OUTPUT_PIN, gpio_get_level(INPUT_PIN));
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

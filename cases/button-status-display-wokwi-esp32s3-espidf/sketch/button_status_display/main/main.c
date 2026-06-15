#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define BUTTON_PIN GPIO_NUM_12

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLUP_ONLY);
  int was_pressed = 0;
  while (1) {
    int pressed = gpio_get_level(BUTTON_PIN) == 0;
    if (pressed && !was_pressed) {
      printf("Button Pressed!\n");
    }
    was_pressed = pressed;
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

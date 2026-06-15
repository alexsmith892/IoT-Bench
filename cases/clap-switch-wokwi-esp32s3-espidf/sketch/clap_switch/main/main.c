#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define SOUND_PIN GPIO_NUM_14
#define RELAY_PIN GPIO_NUM_21

void app_main(void) {
  gpio_reset_pin(SOUND_PIN);
  gpio_set_direction(SOUND_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(RELAY_PIN);
  gpio_set_direction(RELAY_PIN, GPIO_MODE_OUTPUT);
  int last = 0;
  int relay = 0;
  while (1) {
    int sound = gpio_get_level(SOUND_PIN);
    if (sound && !last) {
      relay = !relay;
      gpio_set_level(RELAY_PIN, relay);
    }
    last = sound;
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

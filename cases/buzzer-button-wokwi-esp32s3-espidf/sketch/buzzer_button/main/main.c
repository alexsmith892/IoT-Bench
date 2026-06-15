#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define BUTTON_PIN GPIO_NUM_12
#define BUZZER_PIN GPIO_NUM_13
#define DEBOUNCE_US 30000

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLUP_ONLY);
  gpio_reset_pin(BUZZER_PIN);
  gpio_set_direction(BUZZER_PIN, GPIO_MODE_OUTPUT);
  int stable = 0;
  int last_reading = 0;
  int64_t changed_at = esp_timer_get_time();
  while (1) {
    int reading = gpio_get_level(BUTTON_PIN) == 0;
    int64_t now = esp_timer_get_time();
    if (reading != last_reading) {
      last_reading = reading;
      changed_at = now;
    }
    if (now - changed_at >= DEBOUNCE_US && stable != reading) {
      stable = reading;
    }
    gpio_set_level(BUZZER_PIN, stable);
    vTaskDelay(pdMS_TO_TICKS(1));
  }
}

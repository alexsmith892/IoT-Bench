#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define LED1_PIN GPIO_NUM_10
#define LED2_PIN GPIO_NUM_11

void app_main(void) {
  gpio_reset_pin(LED1_PIN);
  gpio_set_direction(LED1_PIN, GPIO_MODE_OUTPUT);
  gpio_reset_pin(LED2_PIN);
  gpio_set_direction(LED2_PIN, GPIO_MODE_OUTPUT);
  int led1 = 0;
  int led2 = 0;
  int64_t last_led1_us = esp_timer_get_time();
  int64_t last_led2_us = last_led1_us;
  while (1) {
    int64_t now = esp_timer_get_time();
    if (now - last_led1_us >= 500000) {
      last_led1_us += 500000;
      led1 = !led1;
      gpio_set_level(LED1_PIN, led1);
    }
    if (now - last_led2_us >= 250000) {
      last_led2_us += 250000;
      led2 = !led2;
      gpio_set_level(LED2_PIN, led2);
    }
    taskYIELD();
  }
}

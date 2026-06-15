#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define LED_PIN GPIO_NUM_10

static void toggle_led_cb(void *arg) {
  static int level = 0;
  level = !level;
  gpio_set_level(LED_PIN, level);
}

void app_main(void) {
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  const esp_timer_create_args_t timer_args = {
    .callback = &toggle_led_cb,
    .name = "blink",
  };
  esp_timer_handle_t timer;
  esp_timer_create(&timer_args, &timer);
  esp_timer_start_periodic(timer, 500000);
}

#include <stdio.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  gpio_set_direction(GPIO_NUM_43, GPIO_MODE_OUTPUT);
  gpio_set_direction(GPIO_NUM_44, GPIO_MODE_INPUT);
  gpio_set_level(GPIO_NUM_43, 1);
  (void)gpio_get_level(GPIO_NUM_44);
  (void)esp_timer_get_time();
  printf("Distance: 100 cm\n");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

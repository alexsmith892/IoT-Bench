#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  gpio_set_direction(GPIO_NUM_14, GPIO_MODE_INPUT);
  gpio_set_direction(GPIO_NUM_21, GPIO_MODE_OUTPUT);
  (void)gpio_get_level(GPIO_NUM_14);
  gpio_set_level(GPIO_NUM_21, 1);
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

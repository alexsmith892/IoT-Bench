#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  (void)gpio_get_level(GPIO_NUM_12);
  (void)gpio_get_level(GPIO_NUM_14);
  (void)esp_timer_get_time();
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

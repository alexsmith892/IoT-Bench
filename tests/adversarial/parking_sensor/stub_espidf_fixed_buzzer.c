#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  gpio_set_direction(GPIO_NUM_10, GPIO_MODE_OUTPUT);
  gpio_set_direction(GPIO_NUM_40, GPIO_MODE_OUTPUT);
  gpio_set_direction(GPIO_NUM_41, GPIO_MODE_INPUT);
  (void)gpio_get_level(GPIO_NUM_41);
  (void)esp_timer_get_time();
  ledc_set_freq(LEDC_LOW_SPEED_MODE, LEDC_TIMER_0, 2000);
  gpio_set_level(GPIO_NUM_10, 1);
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

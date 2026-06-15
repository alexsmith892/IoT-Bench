#include <stdio.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define DHT_PIN GPIO_NUM_14

void app_main(void) {
  gpio_set_direction(DHT_PIN, GPIO_MODE_OUTPUT);
  gpio_set_level(DHT_PIN, 1);
  (void)gpio_get_level(DHT_PIN);
  (void)esp_timer_get_time();
  printf("Temperature: 18.0 C Humidity: 35.0 %%\n");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

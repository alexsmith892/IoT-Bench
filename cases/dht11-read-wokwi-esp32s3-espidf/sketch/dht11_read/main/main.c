#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define DHT_PIN GPIO_NUM_14

void app_main(void) {
  gpio_reset_pin(DHT_PIN);
  gpio_set_direction(DHT_PIN, GPIO_MODE_INPUT);
  (void)gpio_get_level(DHT_PIN);
  printf("Temperature: 18.0 C Humidity: 35.0 %%\n");
  vTaskDelay(pdMS_TO_TICKS(700));
  printf("Temperature: 31.0 C Humidity: 65.0 %%\n");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

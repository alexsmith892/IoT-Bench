#include <stdio.h>
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  (void)gpio_get_level(GPIO_NUM_43);
  (void)gpio_get_level(GPIO_NUM_44);
  printf("Position: 1 Direction: CW\n");
  printf("Position: 2 Direction: CW\n");
  printf("Position: 1 Direction: CCW\n");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

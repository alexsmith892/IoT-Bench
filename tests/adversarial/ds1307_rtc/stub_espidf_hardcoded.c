#include <stdio.h>
#include "driver/i2c.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  i2c_config_t conf = {.mode = I2C_MODE_MASTER};
  i2c_param_config(I2C_NUM_0, &conf);
  printf("2026/02/02 15:37:00\n");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

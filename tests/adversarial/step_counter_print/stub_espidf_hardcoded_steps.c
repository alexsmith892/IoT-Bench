#include <stdio.h>
#include "driver/i2c.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  i2c_cmd_handle_t cmd = i2c_cmd_link_create();
  i2c_cmd_link_delete(cmd);
  (void)esp_timer_get_time();
  printf("Steps: 1\n");
  printf("Steps: 2\n");
  printf("Steps: 3\n");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define CLK_PIN GPIO_NUM_43
#define DT_PIN GPIO_NUM_44

void app_main(void) {
  gpio_reset_pin(CLK_PIN);
  gpio_reset_pin(DT_PIN);
  gpio_set_direction(CLK_PIN, GPIO_MODE_INPUT);
  gpio_set_direction(DT_PIN, GPIO_MODE_INPUT);
  int last_clk = gpio_get_level(CLK_PIN);
  int position = 0;
  while (1) {
    int clk = gpio_get_level(CLK_PIN);
    if (clk != last_clk && clk == 0) {
      int dt = gpio_get_level(DT_PIN);
      position += dt ? -1 : 1;
      printf("Position: %d Direction: %s\n", position, dt ? "CCW" : "CW");
    }
    last_clk = clk;
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

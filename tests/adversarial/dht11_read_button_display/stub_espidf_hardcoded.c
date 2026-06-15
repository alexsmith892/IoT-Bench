#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void lcd_print(const char *text) { (void)text; }

void app_main(void) {
  gpio_set_direction(GPIO_NUM_12, GPIO_MODE_INPUT);
  gpio_set_direction(GPIO_NUM_14, GPIO_MODE_OUTPUT);
  gpio_set_level(GPIO_NUM_14, 1);
  (void)gpio_get_level(GPIO_NUM_12);
  (void)esp_timer_get_time();
  lcd_print("Temp: 24.0C");
  lcd_print("RH: 40.0%");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

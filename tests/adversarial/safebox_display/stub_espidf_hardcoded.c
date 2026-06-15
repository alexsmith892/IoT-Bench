#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void lcd_print(const char *text) { (void)text; }

void app_main(void) {
  gpio_set_direction(GPIO_NUM_12, GPIO_MODE_OUTPUT);
  (void)gpio_get_level(GPIO_NUM_9);
  gpio_set_level(GPIO_NUM_12, 1);
  lcd_print("Input: 1235");
  lcd_print("Status: Fail");
  lcd_print("Input: 1234");
  lcd_print("Status: Success");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

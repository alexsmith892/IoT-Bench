#include "driver/gpio.h"
#include "driver/i2c.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void lcd_print(const char *text) { (void)text; }

void app_main(void) {
  i2c_config_t conf = {.mode = I2C_MODE_MASTER};
  i2c_param_config(I2C_NUM_0, &conf);
  (void)gpio_get_level(GPIO_NUM_12);
  lcd_print("Accel: 0 0 16384");
  lcd_print("Gyro: 0 0 0");
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

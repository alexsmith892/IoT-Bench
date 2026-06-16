#include "driver/adc.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  adc_oneshot_unit_handle_t unit = 0;
  int value = 0;
  adc_oneshot_read(unit, ADC_CHANNEL_8, &value);
  gpio_set_direction(GPIO_NUM_10, GPIO_MODE_OUTPUT);
  gpio_set_direction(GPIO_NUM_11, GPIO_MODE_OUTPUT);
  gpio_set_level(GPIO_NUM_10, 1);
  gpio_set_level(GPIO_NUM_11, 1);
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

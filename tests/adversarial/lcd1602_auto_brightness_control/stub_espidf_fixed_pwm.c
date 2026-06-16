#include "driver/adc.h"
#include "driver/ledc.h"
#include "esp_adc/adc_oneshot.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  adc_oneshot_unit_handle_t unit = 0;
  int value = 0;
  adc_oneshot_read(unit, ADC_CHANNEL_8, &value);
  ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 128);
  while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

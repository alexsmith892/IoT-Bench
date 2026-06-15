#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_adc/adc_oneshot.h"

#define TMP36_CHANNEL ADC_CHANNEL_8

void app_main(void) {
  adc_oneshot_unit_handle_t adc_handle;
  adc_oneshot_unit_init_cfg_t init_config = {
    .unit_id = ADC_UNIT_1,
  };
  adc_oneshot_new_unit(&init_config, &adc_handle);
  adc_oneshot_chan_cfg_t channel_config = {
    .atten = ADC_ATTEN_DB_12,
    .bitwidth = ADC_BITWIDTH_12,
  };
  adc_oneshot_config_channel(adc_handle, TMP36_CHANNEL, &channel_config);

  while (1) {
    int raw = 0;
    adc_oneshot_read(adc_handle, TMP36_CHANNEL, &raw);
    float voltage = raw * (3.3f / 4095.0f);
    float celsius = (voltage - 0.5f) * 100.0f;
    printf("%.1f\n", celsius);
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}

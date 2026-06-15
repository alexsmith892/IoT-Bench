#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_adc/adc_oneshot.h"

static adc_oneshot_unit_handle_t adc_handle;

static void adc_gpio9_init(void) {
  adc_oneshot_unit_init_cfg_t init_config = {.unit_id = ADC_UNIT_1};
  adc_oneshot_new_unit(&init_config, &adc_handle);
  adc_oneshot_chan_cfg_t channel_config = {
    .atten = ADC_ATTEN_DB_12,
    .bitwidth = ADC_BITWIDTH_12,
  };
  adc_oneshot_config_channel(adc_handle, ADC_CHANNEL_8, &channel_config);
}

static int adc_gpio9_read(void) {
  int raw = 0;
  adc_oneshot_read(adc_handle, ADC_CHANNEL_8, &raw);
  return raw;
}
#define LASER_PIN GPIO_NUM_10
#define BUZZER_PIN GPIO_NUM_11

void app_main(void) {
  adc_gpio9_init();
  gpio_reset_pin(LASER_PIN);
  gpio_set_direction(LASER_PIN, GPIO_MODE_OUTPUT);
  gpio_reset_pin(BUZZER_PIN);
  gpio_set_direction(BUZZER_PIN, GPIO_MODE_OUTPUT);
  gpio_set_level(LASER_PIN, 1);
  while (1) {
    int raw = adc_gpio9_read();
    gpio_set_level(BUZZER_PIN, raw < 1200);
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

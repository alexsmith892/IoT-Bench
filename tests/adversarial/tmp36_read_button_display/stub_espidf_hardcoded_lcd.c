#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"

void app_main(void) {
  adc_oneshot_unit_handle_t unit = 0;
  int value = 0;
  adc_oneshot_read(unit, ADC_CHANNEL_8, &value);
  (void)gpio_get_level(GPIO_NUM_12);
}

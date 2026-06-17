// Adversarial print-only stub for sensor_water_level_display.
//
// Prints a plausible water level without reading the ADC or driving the LCD/GPIO,
// so the static gate's required-pattern check (adc_oneshot_read / gpio_set_level)
// rejects it before simulation.
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  while (1) {
    printf("Water level: 50%%\n");
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

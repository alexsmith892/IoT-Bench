// Adversarial print-only stub for tilt_detection_alarm.
//
// Emits a plausible tilt/alarm narrative but never reads or drives a GPIO, so
// the static gate's required-pattern check (gpio_get_level / gpio_set_level)
// rejects it before simulation.
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  while (1) {
    printf("Tilt detected: alarm on\n");
    vTaskDelay(pdMS_TO_TICKS(500));
    printf("Level: alarm off\n");
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

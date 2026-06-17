// Adversarial print-only stub for hcsr501_motion_alarm.
//
// Prints a plausible motion/alarm narrative but performs no real GPIO I/O, so
// the static gate's required-pattern check (gpio_get_level / gpio_set_level)
// rejects it before simulation. A missing real I/O path is a legitimate failure
// because the library policy bans third-party drivers.
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  while (1) {
    printf("Motion detected: alarm on\n");
    vTaskDelay(pdMS_TO_TICKS(500));
    printf("No motion: alarm off\n");
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

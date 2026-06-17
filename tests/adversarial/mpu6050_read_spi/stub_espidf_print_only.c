// Adversarial print-only stub for mpu6050_read_spi.
//
// Prints fixed accelerometer/gyro numbers without ever touching the SPI bus, so
// the static gate's required-pattern check (spi_) rejects it before simulation.
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
  while (1) {
    printf("ax=0.00 ay=0.00 az=1.00 gx=0.0 gy=0.0 gz=0.0\n");
    vTaskDelay(pdMS_TO_TICKS(200));
  }
}

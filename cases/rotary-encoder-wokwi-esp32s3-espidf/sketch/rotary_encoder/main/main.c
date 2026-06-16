#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define CLK_PIN GPIO_NUM_5
#define DT_PIN GPIO_NUM_6

// Quadrature transition table indexed by (previous << 2) | current, where each
// 2-bit state is (CLK << 1) | DT. Valid edges contribute +1 (CW) or -1 (CCW);
// four sub-steps make one detent. The CLK/DT lines idle high (external
// pull-ups) and are pulled low through the encoder contacts.
static const int8_t QUAD[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};

static int read_state(void) {
  return (gpio_get_level(CLK_PIN) << 1) | gpio_get_level(DT_PIN);
}

void app_main(void) {
  gpio_reset_pin(CLK_PIN);
  gpio_reset_pin(DT_PIN);
  gpio_set_direction(CLK_PIN, GPIO_MODE_INPUT);
  gpio_set_direction(DT_PIN, GPIO_MODE_INPUT);
  int last_state = read_state();
  int sub_step = 0;
  long position = 0;
  while (1) {
    int state = read_state();
    if (state != last_state) {
      sub_step += QUAD[(last_state << 2) | state];
      last_state = state;
      if (sub_step >= 4) {
        sub_step = 0;
        position++;
        printf("Position: %ld Direction: CW\n", position);
      } else if (sub_step <= -4) {
        sub_step = 0;
        position--;
        printf("Position: %ld Direction: CCW\n", position);
      }
    }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

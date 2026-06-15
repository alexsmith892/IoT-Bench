#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/ledc.h"

#define LED_PIN GPIO_NUM_10
#define LEDC_DUTY_MAX 1023

void app_main(void) {
  ledc_timer_config_t timer = {
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .timer_num = LEDC_TIMER_0,
    .duty_resolution = LEDC_TIMER_10_BIT,
    .freq_hz = 1000,
    .clk_cfg = LEDC_AUTO_CLK,
  };
  ledc_timer_config(&timer);
  ledc_channel_config_t channel = {
    .gpio_num = LED_PIN,
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .channel = LEDC_CHANNEL_0,
    .intr_type = LEDC_INTR_DISABLE,
    .timer_sel = LEDC_TIMER_0,
    .duty = 0,
    .hpoint = 0,
  };
  ledc_channel_config(&channel);

  while (1) {
    for (int level = 1; level <= 50; ++level) {
      ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, level * LEDC_DUTY_MAX / 50);
      ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
      vTaskDelay(pdMS_TO_TICKS(10));
    }
    for (int level = 50; level >= 1; --level) {
      ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, level * LEDC_DUTY_MAX / 50);
      ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
      vTaskDelay(pdMS_TO_TICKS(10));
    }
  }
}

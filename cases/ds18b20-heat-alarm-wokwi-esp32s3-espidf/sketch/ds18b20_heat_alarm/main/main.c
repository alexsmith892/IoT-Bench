#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/ledc.h"

static void ledc_tone_init(gpio_num_t pin) {
  ledc_timer_config_t timer = {
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .timer_num = LEDC_TIMER_1,
    .duty_resolution = LEDC_TIMER_10_BIT,
    .freq_hz = 1000,
    .clk_cfg = LEDC_AUTO_CLK,
  };
  ledc_timer_config(&timer);
  ledc_channel_config_t channel = {
    .gpio_num = pin,
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .channel = LEDC_CHANNEL_1,
    .intr_type = LEDC_INTR_DISABLE,
    .timer_sel = LEDC_TIMER_1,
    .duty = 0,
    .hpoint = 0,
  };
  ledc_channel_config(&channel);
}

static void ledc_tone(int freq_hz) {
  if (freq_hz <= 0) {
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 0);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
    return;
  }
  ledc_set_freq(LEDC_LOW_SPEED_MODE, LEDC_TIMER_1, freq_hz);
  ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 512);
  ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
}
#define SENSOR_PIN GPIO_NUM_14
#define LED_PIN GPIO_NUM_10
#define BUZZER_PIN GPIO_NUM_11

void app_main(void) {
  gpio_reset_pin(SENSOR_PIN);
  gpio_set_direction(SENSOR_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(SENSOR_PIN, GPIO_PULLDOWN_ONLY);
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  ledc_tone_init(BUZZER_PIN);
  while (1) {
    int hot = gpio_get_level(SENSOR_PIN);
    if (hot) {
      gpio_set_level(LED_PIN, 1);
      ledc_tone(1200);
    } else {
      gpio_set_level(LED_PIN, 0);
      ledc_tone(0);
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

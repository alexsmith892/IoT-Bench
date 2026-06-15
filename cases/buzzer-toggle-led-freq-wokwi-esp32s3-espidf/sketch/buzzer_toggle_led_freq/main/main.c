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
#define BUTTON_PIN GPIO_NUM_12
#define LED_PIN GPIO_NUM_11
#define BUZZER_PIN GPIO_NUM_10

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  ledc_tone_init(BUZZER_PIN);
  int mode = 0, last = 0, led = 0;
  int64_t last_toggle = esp_timer_get_time();
  int64_t beep_until = 0;
  while (1) {
    int pressed = gpio_get_level(BUTTON_PIN);
    int64_t now = esp_timer_get_time();
    if (pressed && !last) {
      mode = (mode + 1) % 4;
      ledc_tone(2000);
      beep_until = now + 80000;
    }
    last = pressed;
    if (beep_until && now > beep_until) {
      ledc_tone(0);
      beep_until = 0;
    }
    int interval = mode == 1 ? 500000 : (mode == 2 ? 250000 : (mode == 3 ? 125000 : 0));
    if (interval == 0) {
      gpio_set_level(LED_PIN, 0);
    } else if (now - last_toggle >= interval) {
      last_toggle = now;
      led = !led;
      gpio_set_level(LED_PIN, led);
    }
    vTaskDelay(pdMS_TO_TICKS(1));
  }
}

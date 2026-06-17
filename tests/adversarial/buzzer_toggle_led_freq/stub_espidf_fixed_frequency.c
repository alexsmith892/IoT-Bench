// Adversarial decoy for buzzer_toggle_led_freq.
//
// Satisfies the static gate (reads the button with gpio_get_level, drives the
// buzzer through the LEDC peripheral, and uses esp_timer) but ignores the
// button entirely: the LED blinks at a single fixed ~2 Hz rate instead of
// cycling 1 Hz -> 2 Hz -> 4 Hz with each press. The frequency_windows oracle
// rejects it at runtime because the early (slow) and late (fast) windows can
// never both match one hardcoded period.
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define BUTTON_PIN GPIO_NUM_12
#define LED_PIN GPIO_NUM_11
#define BUZZER_PIN GPIO_NUM_10

void app_main(void) {
  gpio_reset_pin(BUTTON_PIN);
  gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT);
  gpio_set_pull_mode(BUTTON_PIN, GPIO_PULLDOWN_ONLY);
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);

  ledc_timer_config_t timer = {
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .timer_num = LEDC_TIMER_1,
    .duty_resolution = LEDC_TIMER_10_BIT,
    .freq_hz = 2000,
    .clk_cfg = LEDC_AUTO_CLK,
  };
  ledc_timer_config(&timer);
  ledc_channel_config_t channel = {
    .gpio_num = BUZZER_PIN,
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .channel = LEDC_CHANNEL_1,
    .timer_sel = LEDC_TIMER_1,
    .duty = 512,
    .hpoint = 0,
  };
  ledc_channel_config(&channel);

  int led = 0;
  int64_t last = esp_timer_get_time();
  while (1) {
    (void)gpio_get_level(BUTTON_PIN);
    int64_t now = esp_timer_get_time();
    if (now - last >= 250000) {
      last = now;
      led = !led;
      gpio_set_level(LED_PIN, led);
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

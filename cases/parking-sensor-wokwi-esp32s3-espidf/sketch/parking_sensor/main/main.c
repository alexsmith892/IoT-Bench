#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/ledc.h"
#include "esp_rom_sys.h"

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
#define TRIG_PIN GPIO_NUM_40
#define ECHO_PIN GPIO_NUM_41

static int read_distance_cm(void) {
  gpio_set_level(TRIG_PIN, 0);
  esp_rom_delay_us(2);
  gpio_set_level(TRIG_PIN, 1);
  esp_rom_delay_us(10);
  gpio_set_level(TRIG_PIN, 0);
  int64_t timeout = esp_timer_get_time() + 30000;
  while (!gpio_get_level(ECHO_PIN) && esp_timer_get_time() < timeout) {}
  int64_t start = esp_timer_get_time();
  while (gpio_get_level(ECHO_PIN) && esp_timer_get_time() < timeout) {}
  int64_t duration = esp_timer_get_time() - start;
  if (duration <= 0 || duration > 30000) return -1;
  return (int)(duration / 58);
}
#define LED_PIN GPIO_NUM_10
#define BUZZER_PIN GPIO_NUM_11

void app_main(void) {
  gpio_reset_pin(TRIG_PIN);
  gpio_set_direction(TRIG_PIN, GPIO_MODE_OUTPUT);
  gpio_reset_pin(ECHO_PIN);
  gpio_set_direction(ECHO_PIN, GPIO_MODE_INPUT);
  gpio_reset_pin(LED_PIN);
  gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
  ledc_tone_init(BUZZER_PIN);
  while (1) {
    int distance = read_distance_cm();
    gpio_set_level(LED_PIN, distance > 0 && distance < 80);
    ledc_tone(distance > 0 && distance < 40 ? 2000 : (distance > 0 && distance < 80 ? 1000 : 0));
    vTaskDelay(pdMS_TO_TICKS(60));
  }
}

#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_rom_sys.h"

#define TRIG_PIN GPIO_NUM_43
#define ECHO_PIN GPIO_NUM_44

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
void app_main(void) {
  gpio_reset_pin(TRIG_PIN);
  gpio_set_direction(TRIG_PIN, GPIO_MODE_OUTPUT);
  gpio_reset_pin(ECHO_PIN);
  gpio_set_direction(ECHO_PIN, GPIO_MODE_INPUT);
  while (1) {
    int distance = read_distance_cm();
    printf("Distance: %d cm\n", distance);
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}

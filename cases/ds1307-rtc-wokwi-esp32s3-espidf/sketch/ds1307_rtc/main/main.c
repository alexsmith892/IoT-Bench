#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c.h"

#define I2C_PORT I2C_NUM_0

static void i2c_setup(void) {
  i2c_config_t conf = {
    .mode = I2C_MODE_MASTER,
    .sda_io_num = GPIO_NUM_38,
    .scl_io_num = GPIO_NUM_39,
    .sda_pullup_en = GPIO_PULLUP_ENABLE,
    .scl_pullup_en = GPIO_PULLUP_ENABLE,
    .master.clk_speed = 100000,
  };
  i2c_param_config(I2C_PORT, &conf);
  i2c_driver_install(I2C_PORT, conf.mode, 0, 0, 0);
}

static uint8_t i2c_read_reg(uint8_t addr, uint8_t reg) {
  uint8_t value = 0;
  i2c_master_write_read_device(I2C_PORT, addr, &reg, 1, &value, 1, pdMS_TO_TICKS(50));
  return value;
}

static void i2c_write_reg(uint8_t addr, uint8_t reg, uint8_t value) {
  uint8_t data[2] = {reg, value};
  i2c_master_write_to_device(I2C_PORT, addr, data, sizeof(data), pdMS_TO_TICKS(50));
}
static int from_bcd(uint8_t value) {
  return ((value >> 4) * 10) + (value & 0x0f);
}

void app_main(void) {
  i2c_setup();
  while (1) {
    uint8_t reg = 0x00;
    uint8_t data[7] = {0};
    if (i2c_master_write_read_device(I2C_PORT, 0x68, &reg, 1, data, sizeof(data), pdMS_TO_TICKS(50)) == 0) {
      int second = from_bcd(data[0] & 0x7f);
      int minute = from_bcd(data[1]);
      int hour = from_bcd(data[2] & 0x3f);
      int day = from_bcd(data[4]);
      int month = from_bcd(data[5]);
      int year = 2000 + from_bcd(data[6]);
      printf("%04d/%02d/%02d %02d:%02d:%02d\n", year, month, day, hour, minute, second);
    }
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}

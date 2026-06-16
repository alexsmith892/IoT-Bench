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
// MPU6050 default range is +/-2g => 16384 LSB/g. A "step" is a Z-axis
// acceleration spike above ~1.5g; we re-arm once motion settles back below
// ~1.25g so each spike is counted exactly once.
#define SPIKE_C (24000)
#define REARM_C (20000)

void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);  // wake device
  int steps = 0;
  int armed = 1;
  while (1) {
    uint8_t hi = i2c_read_reg(0x68, 0x3f);  // ACCEL_ZOUT_H
    uint8_t lo = i2c_read_reg(0x68, 0x40);  // ACCEL_ZOUT_L
    int16_t az = (int16_t)((hi << 8) | lo);
    int mag = az < 0 ? -az : az;
    if (armed && mag > SPIKE_C) {
      armed = 0;
      printf("Steps: %d\n", ++steps);
    } else if (mag < REARM_C) {
      armed = 1;
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

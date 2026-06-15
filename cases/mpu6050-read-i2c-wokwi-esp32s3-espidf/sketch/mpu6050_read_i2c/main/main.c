#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
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
static int16_t mpu_word(const uint8_t *data, int offset) {
  return (int16_t)((data[offset] << 8) | data[offset + 1]);
}

static void read_mpu6050_raw(int16_t *ax, int16_t *ay, int16_t *az, int16_t *gx, int16_t *gy, int16_t *gz) {
  uint8_t reg = 0x3b;
  uint8_t data[14] = {0};
  i2c_master_write_read_device(I2C_PORT, 0x68, &reg, 1, data, sizeof(data), pdMS_TO_TICKS(50));
  *ax = mpu_word(data, 0);
  *ay = mpu_word(data, 2);
  *az = mpu_word(data, 4);
  *gx = mpu_word(data, 8);
  *gy = mpu_word(data, 10);
  *gz = mpu_word(data, 12);
}

void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);
  while (1) {
    int16_t ax, ay, az, gx, gy, gz;
    read_mpu6050_raw(&ax, &ay, &az, &gx, &gy, &gz);
    printf("Accel: %d %d %d Gyro: %d %d %d\n", ax, ay, az, gx, gy, gz);
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}

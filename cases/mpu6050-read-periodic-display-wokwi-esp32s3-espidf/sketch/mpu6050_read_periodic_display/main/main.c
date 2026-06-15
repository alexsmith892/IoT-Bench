#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c.h"
#include "esp_rom_sys.h"

#define I2C_PORT I2C_NUM_0

static void i2c_setup(void) {
  i2c_config_t conf = {
    .mode = I2C_MODE_MASTER,
    .sda_io_num = GPIO_NUM_9,
    .scl_io_num = GPIO_NUM_10,
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

#define LCD_RS GPIO_NUM_38
#define LCD_E GPIO_NUM_39
#define LCD_D4 GPIO_NUM_40
#define LCD_D5 GPIO_NUM_41
#define LCD_D6 GPIO_NUM_42
#define LCD_D7 GPIO_NUM_21

static void lcd_gpio_init(void) {
  const gpio_num_t pins[] = {LCD_RS, LCD_E, LCD_D4, LCD_D5, LCD_D6, LCD_D7};
  for (int i = 0; i < 6; ++i) {
    gpio_reset_pin(pins[i]);
    gpio_set_direction(pins[i], GPIO_MODE_OUTPUT);
  }
}

static void lcd_pulse(void) {
  gpio_set_level(LCD_E, 1);
  esp_rom_delay_us(1);
  gpio_set_level(LCD_E, 0);
  esp_rom_delay_us(60);
}

static void lcd_nibble(uint8_t value) {
  gpio_set_level(LCD_D4, value & 1);
  gpio_set_level(LCD_D5, (value >> 1) & 1);
  gpio_set_level(LCD_D6, (value >> 2) & 1);
  gpio_set_level(LCD_D7, (value >> 3) & 1);
  lcd_pulse();
}

static void lcd_write(uint8_t value, int rs) {
  gpio_set_level(LCD_RS, rs);
  lcd_nibble(value >> 4);
  lcd_nibble(value & 0x0f);
}

static void lcd_command(uint8_t value) {
  lcd_write(value, 0);
  if (value == 1) {
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

static void lcd_data(uint8_t value) {
  lcd_write(value, 1);
}

static void lcd_begin(void) {
  lcd_gpio_init();
  vTaskDelay(pdMS_TO_TICKS(50));
  lcd_command(0x28);
  lcd_command(0x0c);
  lcd_command(0x06);
  lcd_command(0x01);
}

static void lcd_clear(void) { lcd_command(0x01); }
static void lcd_set_cursor(int col, int row) { lcd_command((row ? 0xc0 : 0x80) + col); }
static void lcd_print(const char *text) {
  while (*text) {
    lcd_data((uint8_t)*text++);
  }
}
static void display_average(int32_t ax, int32_t ay, int32_t az, int32_t gx, int32_t gy, int32_t gz) {
  char line[32];
  lcd_clear();
  lcd_set_cursor(0, 0);
  snprintf(line, sizeof(line), "Accel: %ld %ld", (long)ax, (long)ay);
  lcd_print(line);
  lcd_set_cursor(0, 1);
  snprintf(line, sizeof(line), "Gyro: %ld %ld", (long)gx, (long)gy);
  lcd_print(line);
}

void app_main(void) {
  i2c_setup();
  i2c_write_reg(0x68, 0x6b, 0);
  lcd_begin();

  int16_t ax_buf[10] = {0}, ay_buf[10] = {0}, az_buf[10] = {0};
  int16_t gx_buf[10] = {0}, gy_buf[10] = {0}, gz_buf[10] = {0};
  int sample_count = 0;
  int sample_index = 0;
  int64_t next_sample_us = esp_timer_get_time();

  while (1) {
    int64_t now = esp_timer_get_time();
    if (now >= next_sample_us) {
      int16_t ax, ay, az, gx, gy, gz;
      read_mpu6050_raw(&ax, &ay, &az, &gx, &gy, &gz);
      ax_buf[sample_index] = ax;
      ay_buf[sample_index] = ay;
      az_buf[sample_index] = az;
      gx_buf[sample_index] = gx;
      gy_buf[sample_index] = gy;
      gz_buf[sample_index] = gz;
      sample_index = (sample_index + 1) % 10;
      if (sample_count < 10) sample_count++;

      int32_t sum_ax = 0, sum_ay = 0, sum_az = 0, sum_gx = 0, sum_gy = 0, sum_gz = 0;
      for (int i = 0; i < sample_count; ++i) {
        sum_ax += ax_buf[i];
        sum_ay += ay_buf[i];
        sum_az += az_buf[i];
        sum_gx += gx_buf[i];
        sum_gy += gy_buf[i];
        sum_gz += gz_buf[i];
      }
      display_average(sum_ax / sample_count, sum_ay / sample_count, sum_az / sample_count,
                      sum_gx / sample_count, sum_gy / sample_count, sum_gz / sample_count);
      next_sample_us += 100000;
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

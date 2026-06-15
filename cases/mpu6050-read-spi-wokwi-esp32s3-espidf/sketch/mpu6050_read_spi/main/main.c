#include <stdio.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/spi_master.h"

static spi_device_handle_t spi_dev;

static void spi_setup(void) {
  spi_bus_config_t buscfg = {
    .miso_io_num = GPIO_NUM_37,
    .mosi_io_num = GPIO_NUM_36,
    .sclk_io_num = GPIO_NUM_35,
    .quadwp_io_num = -1,
    .quadhd_io_num = -1,
  };
  spi_device_interface_config_t devcfg = {
    .clock_speed_hz = 1000000,
    .mode = 0,
    .spics_io_num = GPIO_NUM_14,
    .queue_size = 1,
  };
  spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_DISABLED);
  spi_bus_add_device(SPI2_HOST, &devcfg, &spi_dev);
}

static uint8_t spi_transfer(uint8_t byte) {
  uint8_t rx = 0;
  spi_transaction_t t = {
    .length = 8,
    .tx_buffer = &byte,
    .rx_buffer = &rx,
  };
  spi_device_transmit(spi_dev, &t);
  return rx;
}
static uint8_t mpu_spi_read_reg(uint8_t reg) {
  uint8_t command = 0x80 | reg;
  uint8_t rx[2] = {0, 0};
  uint8_t tx[2] = {command, 0};
  spi_transaction_t t = {
    .length = 16,
    .tx_buffer = tx,
    .rx_buffer = rx,
  };
  spi_device_transmit(spi_dev, &t);
  return rx[1];
}

static void mpu_spi_write_reg(uint8_t reg, uint8_t value) {
  uint8_t tx[2] = {reg & 0x7f, value};
  spi_transaction_t t = {
    .length = 16,
    .tx_buffer = tx,
  };
  spi_device_transmit(spi_dev, &t);
}

static int16_t mpu_spi_read_word(uint8_t reg) {
  uint8_t high = mpu_spi_read_reg(reg);
  uint8_t low = mpu_spi_read_reg(reg + 1);
  return (int16_t)((high << 8) | low);
}

void app_main(void) {
  spi_setup();
  uint8_t who = mpu_spi_read_reg(0x75);
  mpu_spi_write_reg(0x6b, 0);
  while (1) {
    int16_t ax = mpu_spi_read_word(0x3b);
    int16_t ay = mpu_spi_read_word(0x3d);
    int16_t az = mpu_spi_read_word(0x3f);
    int16_t gx = mpu_spi_read_word(0x43);
    int16_t gy = mpu_spi_read_word(0x45);
    int16_t gz = mpu_spi_read_word(0x47);
    printf("WHO: 0x%02x Accel: %d %d %d Gyro: %d %d %d\n", who, ax, ay, az, gx, gy, gz);
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}

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
    .miso_io_num = GPIO_NUM_40,
    .mosi_io_num = GPIO_NUM_39,
    .sclk_io_num = GPIO_NUM_38,
    .quadwp_io_num = -1,
    .quadhd_io_num = -1,
  };
  spi_device_interface_config_t devcfg = {
    .clock_speed_hz = 1000000,
    .mode = 0,
    .spics_io_num = GPIO_NUM_41,
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
typedef struct {
  float temperature_c;
  float humidity_rh;
  float pressure_pa;
} bme_sample_t;

static const uint16_t dig_T1 = 27504;
static const int16_t dig_T2 = 26435;
static const int16_t dig_T3 = -1000;
static const uint16_t dig_P1 = 36477;
static const int16_t dig_P2 = -10685;
static const int16_t dig_P3 = 3024;
static const int16_t dig_P4 = 2855;
static const int16_t dig_P5 = 140;
static const int16_t dig_P6 = -7;
static const int16_t dig_P7 = 15500;
static const int16_t dig_P8 = -14600;
static const int16_t dig_P9 = 6000;
static const uint8_t dig_H1 = 75;
static const int16_t dig_H2 = 362;
static const uint8_t dig_H3 = 0;
static const int16_t dig_H4 = 325;
static const int16_t dig_H5 = 50;
static const int8_t dig_H6 = 30;
static int32_t bme_t_fine = 0;

static void bme_read_bytes(uint8_t reg, uint8_t *data, size_t len);

static int32_t bme_compensate_temperature(int32_t adc_T) {
  int32_t var1 = ((((adc_T >> 3) - ((int32_t)dig_T1 << 1))) * ((int32_t)dig_T2)) >> 11;
  int32_t var2 = (((((adc_T >> 4) - ((int32_t)dig_T1)) * ((adc_T >> 4) - ((int32_t)dig_T1))) >> 12) * ((int32_t)dig_T3)) >> 14;
  bme_t_fine = var1 + var2;
  return (bme_t_fine * 5 + 128) >> 8;
}

static uint32_t bme_compensate_humidity(int32_t adc_H) {
  int32_t v = bme_t_fine - 76800;
  v = (((((adc_H << 14) - (((int32_t)dig_H4) << 20) - (((int32_t)dig_H5) * v)) + 16384) >> 15) *
       (((((((v * ((int32_t)dig_H6)) >> 10) * (((v * ((int32_t)dig_H3)) >> 11) + 32768)) >> 10) + 2097152) *
             ((int32_t)dig_H2) +
           8192) >>
          14));
  v = v - (((((v >> 15) * (v >> 15)) >> 7) * ((int32_t)dig_H1)) >> 4);
  if (v < 0) {
    v = 0;
  }
  if (v > 419430400) {
    v = 419430400;
  }
  return (uint32_t)(v >> 12);
}

static uint32_t bme_compensate_pressure(int32_t adc_P) {
  int64_t var1 = ((int64_t)bme_t_fine) - 128000;
  int64_t var2 = var1 * var1 * (int64_t)dig_P6;
  var2 = var2 + ((var1 * (int64_t)dig_P5) << 17);
  var2 = var2 + (((int64_t)dig_P4) << 35);
  var1 = ((var1 * var1 * (int64_t)dig_P3) >> 8) + ((var1 * (int64_t)dig_P2) << 12);
  var1 = (((((int64_t)1) << 47) + var1)) * ((int64_t)dig_P1) >> 33;
  if (var1 == 0) {
    return 0;
  }
  int64_t p = 1048576 - adc_P;
  p = (((p << 31) - var2) * 3125) / var1;
  var1 = (((int64_t)dig_P9) * (p >> 13) * (p >> 13)) >> 25;
  var2 = (((int64_t)dig_P8) * p) >> 19;
  p = ((p + var1 + var2) >> 8) + (((int64_t)dig_P7) << 4);
  return (uint32_t)p;
}

static bme_sample_t bme_read_sample(void) {
  uint8_t data[8] = {0};
  bme_read_bytes(0xf7, data, sizeof(data));
  int32_t adc_P = ((int32_t)data[0] << 12) | ((int32_t)data[1] << 4) | (data[2] >> 4);
  int32_t adc_T = ((int32_t)data[3] << 12) | ((int32_t)data[4] << 4) | (data[5] >> 4);
  int32_t adc_H = ((int32_t)data[6] << 8) | data[7];

  int32_t temp_c_x100 = bme_compensate_temperature(adc_T);
  uint32_t pressure_pa_x256 = bme_compensate_pressure(adc_P);
  uint32_t humidity_x1024 = bme_compensate_humidity(adc_H);
  bme_sample_t sample = {
    .temperature_c = temp_c_x100 / 100.0f,
    .humidity_rh = humidity_x1024 / 1024.0f,
    .pressure_pa = pressure_pa_x256 / 256.0f,
  };
  return sample;
}

static void bme_read_bytes(uint8_t reg, uint8_t *data, size_t len) {
  uint8_t tx[9] = {0};
  uint8_t rx[9] = {0};
  if (len > 8) {
    len = 8;
  }
  tx[0] = reg | 0x80;
  spi_transaction_t t = {
    .length = (len + 1) * 8,
    .tx_buffer = tx,
    .rx_buffer = rx,
  };
  spi_device_transmit(spi_dev, &t);
  for (size_t i = 0; i < len; ++i) {
    data[i] = rx[i + 1];
  }
}

static void bme_write_reg(uint8_t reg, uint8_t value) {
  uint8_t tx[2] = {reg & 0x7f, value};
  spi_transaction_t t = {
    .length = 16,
    .tx_buffer = tx,
  };
  spi_device_transmit(spi_dev, &t);
}

void app_main(void) {
  spi_setup();
  uint8_t id = 0;
  bme_read_bytes(0xd0, &id, 1);
  bme_write_reg(0xf2, 0x01);
  bme_write_reg(0xf4, 0x27);
  while (1) {
    bme_sample_t sample = bme_read_sample();
    printf("Temperature: %.1f C Humidity: %.1f %% Pressure: %.0f Pa\n",
           sample.temperature_c, sample.humidity_rh, sample.pressure_pa);
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

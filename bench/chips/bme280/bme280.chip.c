#include "wokwi-api.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#define REG_COUNT 256
#define BME280_CHIP_ID 0x60

typedef struct {
  pin_t cs;
  pin_t sck;
  pin_t sdi;
  pin_t sdo;
  pin_t scl;
  pin_t sda;
  uint32_t temperature_attr;
  uint32_t humidity_attr;
  uint32_t pressure_attr;
  uint8_t regs[REG_COUNT];
  uint8_t i2c_reg;
  bool i2c_expect_reg;
  bool spi_selected;
  bool spi_have_command;
  bool spi_reading;
  uint8_t spi_reg;
  uint8_t spi_in;
  uint8_t spi_in_bits;
  uint8_t spi_out;
  uint8_t spi_out_bits;
} chip_state_t;

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

static void put_u16(chip_state_t *chip, uint8_t reg, uint16_t value) {
  chip->regs[reg] = value & 0xff;
  chip->regs[reg + 1] = value >> 8;
}

static void put_s16(chip_state_t *chip, uint8_t reg, int16_t value) {
  put_u16(chip, reg, (uint16_t)value);
}

static int32_t compensate_temperature(int32_t adc_T, int32_t *t_fine) {
  int32_t var1 = ((((adc_T >> 3) - ((int32_t)dig_T1 << 1))) * ((int32_t)dig_T2)) >> 11;
  int32_t var2 = (((((adc_T >> 4) - ((int32_t)dig_T1)) * ((adc_T >> 4) - ((int32_t)dig_T1))) >> 12) * ((int32_t)dig_T3)) >> 14;
  *t_fine = var1 + var2;
  return ((*t_fine * 5 + 128) >> 8);
}

static uint32_t compensate_humidity(int32_t adc_H, int32_t t_fine) {
  int32_t v = t_fine - 76800;
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

static uint32_t compensate_pressure(int32_t adc_P, int32_t t_fine) {
  int64_t var1 = ((int64_t)t_fine) - 128000;
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

static int32_t abs32(int32_t value) {
  return value < 0 ? -value : value;
}

static uint32_t invert_temperature(float target_c, int32_t *t_fine) {
  int32_t target = (int32_t)(target_c * 100.0f + (target_c >= 0 ? 0.5f : -0.5f));
  uint32_t lo = 0;
  uint32_t hi = 1048575;
  for (uint8_t i = 0; i < 24; ++i) {
    uint32_t mid = (lo + hi) / 2;
    int32_t mid_fine = 0;
    int32_t actual = compensate_temperature((int32_t)mid, &mid_fine);
    if (actual < target) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  uint32_t best = lo;
  int32_t best_fine = 0;
  int32_t best_temp = compensate_temperature((int32_t)best, &best_fine);
  uint32_t start = lo > 8 ? lo - 8 : 0;
  uint32_t end = lo + 8 > 1048575 ? 1048575 : lo + 8;
  for (uint32_t raw = start; raw <= end; ++raw) {
    int32_t raw_fine = 0;
    int32_t actual = compensate_temperature((int32_t)raw, &raw_fine);
    if (abs32(actual - target) < abs32(best_temp - target)) {
      best = raw;
      best_temp = actual;
      best_fine = raw_fine;
    }
  }
  *t_fine = best_fine;
  return best;
}

static uint32_t invert_humidity(float target_rh, int32_t t_fine) {
  uint32_t target = (uint32_t)(target_rh * 1024.0f + 0.5f);
  uint32_t lo = 0;
  uint32_t hi = 65535;
  for (uint8_t i = 0; i < 20; ++i) {
    uint32_t mid = (lo + hi) / 2;
    uint32_t actual = compensate_humidity((int32_t)mid, t_fine);
    if (actual < target) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  uint32_t best = lo;
  uint32_t best_h = compensate_humidity((int32_t)best, t_fine);
  uint32_t start = lo > 16 ? lo - 16 : 0;
  uint32_t end = lo + 16 > 65535 ? 65535 : lo + 16;
  for (uint32_t raw = start; raw <= end; ++raw) {
    uint32_t actual = compensate_humidity((int32_t)raw, t_fine);
    if (abs32((int32_t)actual - (int32_t)target) < abs32((int32_t)best_h - (int32_t)target)) {
      best = raw;
      best_h = actual;
    }
  }
  return best;
}

static uint32_t invert_pressure(float target_pa, int32_t t_fine) {
  uint32_t target = (uint32_t)(target_pa * 256.0f + 0.5f);
  uint32_t lo = 0;
  uint32_t hi = 1048575;
  for (uint8_t i = 0; i < 24; ++i) {
    uint32_t mid = (lo + hi) / 2;
    uint32_t actual = compensate_pressure((int32_t)mid, t_fine);
    if (actual > target) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  uint32_t best = lo;
  uint32_t best_p = compensate_pressure((int32_t)best, t_fine);
  uint32_t start = lo > 16 ? lo - 16 : 0;
  uint32_t end = lo + 16 > 1048575 ? 1048575 : lo + 16;
  for (uint32_t raw = start; raw <= end; ++raw) {
    uint32_t actual = compensate_pressure((int32_t)raw, t_fine);
    if (abs32((int32_t)actual - (int32_t)target) < abs32((int32_t)best_p - (int32_t)target)) {
      best = raw;
      best_p = actual;
    }
  }
  return best;
}

static void load_calibration(chip_state_t *chip) {
  put_u16(chip, 0x88, dig_T1);
  put_s16(chip, 0x8a, dig_T2);
  put_s16(chip, 0x8c, dig_T3);
  put_u16(chip, 0x8e, dig_P1);
  put_s16(chip, 0x90, dig_P2);
  put_s16(chip, 0x92, dig_P3);
  put_s16(chip, 0x94, dig_P4);
  put_s16(chip, 0x96, dig_P5);
  put_s16(chip, 0x98, dig_P6);
  put_s16(chip, 0x9a, dig_P7);
  put_s16(chip, 0x9c, dig_P8);
  put_s16(chip, 0x9e, dig_P9);
  chip->regs[0xa1] = dig_H1;
  put_s16(chip, 0xe1, dig_H2);
  chip->regs[0xe3] = dig_H3;
  chip->regs[0xe4] = (uint8_t)(dig_H4 >> 4);
  chip->regs[0xe5] = (uint8_t)(((dig_H5 & 0x0f) << 4) | (dig_H4 & 0x0f));
  chip->regs[0xe6] = (uint8_t)(dig_H5 >> 4);
  chip->regs[0xe7] = (uint8_t)dig_H6;
}

static void reset_registers(chip_state_t *chip) {
  for (int i = 0; i < REG_COUNT; ++i) {
    chip->regs[i] = 0;
  }
  load_calibration(chip);
  chip->regs[0xd0] = BME280_CHIP_ID;
  chip->regs[0xf2] = 0;
  chip->regs[0xf3] = 0;
  chip->regs[0xf4] = 0;
  chip->regs[0xf5] = 0;
}

static void update_measurement_registers(chip_state_t *chip) {
  float temperature = attr_read_float(chip->temperature_attr);
  float humidity = attr_read_float(chip->humidity_attr);
  float pressure = attr_read_float(chip->pressure_attr);
  if (humidity < 0.0f) {
    humidity = 0.0f;
  }
  if (humidity > 100.0f) {
    humidity = 100.0f;
  }
  int32_t t_fine = 0;
  uint32_t adc_T = invert_temperature(temperature, &t_fine);
  uint32_t adc_H = invert_humidity(humidity, t_fine);
  uint32_t adc_P = invert_pressure(pressure, t_fine);

  chip->regs[0xf7] = (uint8_t)(adc_P >> 12);
  chip->regs[0xf8] = (uint8_t)(adc_P >> 4);
  chip->regs[0xf9] = (uint8_t)((adc_P & 0x0f) << 4);
  chip->regs[0xfa] = (uint8_t)(adc_T >> 12);
  chip->regs[0xfb] = (uint8_t)(adc_T >> 4);
  chip->regs[0xfc] = (uint8_t)((adc_T & 0x0f) << 4);
  chip->regs[0xfd] = (uint8_t)(adc_H >> 8);
  chip->regs[0xfe] = (uint8_t)adc_H;
}

static uint8_t read_reg(chip_state_t *chip, uint8_t reg) {
  if (reg >= 0xf7 && reg <= 0xfe) {
    update_measurement_registers(chip);
  }
  return chip->regs[reg];
}

static void write_reg(chip_state_t *chip, uint8_t reg, uint8_t value) {
  switch (reg) {
  case 0xe0:
    if (value == 0xb6) {
      reset_registers(chip);
    }
    break;
  case 0xf2:
  case 0xf4:
  case 0xf5:
    chip->regs[reg] = value;
    break;
  default:
    break;
  }
}

static bool on_i2c_connect(void *user_data, uint32_t address, bool read) {
  chip_state_t *chip = (chip_state_t *)user_data;
  if (address != 0x76 && address != 0x77) {
    return false;
  }
  if (!read) {
    chip->i2c_expect_reg = true;
  }
  return true;
}

static uint8_t on_i2c_read(void *user_data) {
  chip_state_t *chip = (chip_state_t *)user_data;
  uint8_t value = read_reg(chip, chip->i2c_reg);
  chip->i2c_reg++;
  return value;
}

static bool on_i2c_write(void *user_data, uint8_t data) {
  chip_state_t *chip = (chip_state_t *)user_data;
  if (chip->i2c_expect_reg) {
    chip->i2c_reg = data;
    chip->i2c_expect_reg = false;
  } else {
    write_reg(chip, chip->i2c_reg, data);
    chip->i2c_reg++;
  }
  return true;
}

static void spi_reset(chip_state_t *chip) {
  chip->spi_have_command = false;
  chip->spi_reading = false;
  chip->spi_reg = 0;
  chip->spi_in = 0;
  chip->spi_in_bits = 0;
  chip->spi_out = 0xff;
  chip->spi_out_bits = 0;
  pin_write(chip->sdo, HIGH);
}

static void spi_load_next_out(chip_state_t *chip) {
  chip->spi_out = read_reg(chip, chip->spi_reg);
  chip->spi_reg++;
  chip->spi_out_bits = 0;
}

static void spi_process_byte(chip_state_t *chip, uint8_t value) {
  if (!chip->spi_have_command) {
    chip->spi_have_command = true;
    chip->spi_reading = (value & 0x80) != 0;
    chip->spi_reg = chip->spi_reading ? value : (value | 0x80);
    if (chip->spi_reading) {
      spi_load_next_out(chip);
    }
    return;
  }
  if (chip->spi_reading) {
    return;
  }
  write_reg(chip, chip->spi_reg, value);
  chip->spi_reg++;
}

static void on_cs_change(void *user_data, pin_t pin, uint32_t value) {
  (void)pin;
  chip_state_t *chip = (chip_state_t *)user_data;
  chip->spi_selected = value == LOW;
  spi_reset(chip);
}

static void on_sck_change(void *user_data, pin_t pin, uint32_t value) {
  (void)pin;
  chip_state_t *chip = (chip_state_t *)user_data;
  if (!chip->spi_selected) {
    return;
  }
  if (value == FALLING || value == LOW) {
    if (chip->spi_reading && chip->spi_have_command) {
      uint8_t bit = (chip->spi_out >> (7 - chip->spi_out_bits)) & 1;
      pin_write(chip->sdo, bit ? HIGH : LOW);
    }
    return;
  }

  chip->spi_in = (uint8_t)((chip->spi_in << 1) | (pin_read(chip->sdi) == HIGH ? 1 : 0));
  chip->spi_in_bits++;

  if (chip->spi_reading && chip->spi_have_command) {
    chip->spi_out_bits++;
    if (chip->spi_out_bits >= 8) {
      spi_load_next_out(chip);
    }
  }

  if (chip->spi_in_bits >= 8) {
    spi_process_byte(chip, chip->spi_in);
    chip->spi_in = 0;
    chip->spi_in_bits = 0;
  }
}

void chip_init(void) {
  chip_state_t *chip = malloc(sizeof(chip_state_t));
  chip->temperature_attr = attr_init_float("temperatureC", 24.5f);
  chip->humidity_attr = attr_init_float("humidityRH", 55.0f);
  chip->pressure_attr = attr_init_float("pressurePa", 101325.0f);
  chip->cs = pin_init("CS", INPUT_PULLUP);
  chip->sck = pin_init("SCK", INPUT);
  chip->sdi = pin_init("SDI", INPUT);
  chip->sdo = pin_init("SDO", OUTPUT_HIGH);
  chip->scl = pin_init("SCL", INPUT_PULLUP);
  chip->sda = pin_init("SDA", INPUT_PULLUP);

  reset_registers(chip);
  chip->i2c_reg = 0;
  chip->i2c_expect_reg = true;
  chip->spi_selected = false;
  spi_reset(chip);

  const i2c_config_t i2c = {
      .address = 0,
      .scl = chip->scl,
      .sda = chip->sda,
      .connect = on_i2c_connect,
      .read = on_i2c_read,
      .write = on_i2c_write,
      .disconnect = NULL,
      .user_data = chip,
  };
  i2c_init(&i2c);

  const pin_watch_config_t cs_watch = {
      .edge = BOTH,
      .pin_change = on_cs_change,
      .user_data = chip,
  };
  pin_watch(chip->cs, &cs_watch);

  const pin_watch_config_t sck_watch = {
      .edge = BOTH,
      .pin_change = on_sck_change,
      .user_data = chip,
  };
  pin_watch(chip->sck, &sck_watch);

}

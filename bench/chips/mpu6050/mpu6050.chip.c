#include "../bme280/wokwi-api.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#define REG_COUNT 256
#define REG_GYRO_CONFIG 0x1b
#define REG_ACCEL_CONFIG 0x1c
#define REG_PWR_MGMT_1 0x6b
#define REG_WHO_AM_I 0x75

typedef struct {
  pin_t cs;
  pin_t sck;
  pin_t sdi;
  pin_t sdo;
  uint32_t accel_x_attr;
  uint32_t accel_y_attr;
  uint32_t accel_z_attr;
  uint32_t rotation_x_attr;
  uint32_t rotation_y_attr;
  uint32_t rotation_z_attr;
  uint32_t temperature_attr;
  uint8_t regs[REG_COUNT];
  bool spi_selected;
  bool spi_have_command;
  bool spi_reading;
  uint8_t spi_reg;
  uint8_t spi_in;
  uint8_t spi_in_bits;
  uint8_t spi_out;
  uint8_t spi_out_bits;
} chip_state_t;

static int16_t saturate_round(float value) {
  if (value > 32767.0f) {
    return 32767;
  }
  if (value < -32768.0f) {
    return -32768;
  }
  return (int16_t)(value >= 0.0f ? value + 0.5f : value - 0.5f);
}

static uint8_t high_byte(int16_t value) {
  return (uint8_t)(((uint16_t)value >> 8) & 0xff);
}

static uint8_t low_byte(int16_t value) {
  return (uint8_t)((uint16_t)value & 0xff);
}

static int16_t accel_raw(chip_state_t *chip, float g) {
  uint8_t fs = (chip->regs[REG_ACCEL_CONFIG] >> 3) & 0x03;
  return saturate_round(g * (16384.0f / (float)(1 << fs)));
}

static int16_t gyro_raw(chip_state_t *chip, float dps) {
  uint8_t fs = (chip->regs[REG_GYRO_CONFIG] >> 3) & 0x03;
  return saturate_round(dps * (131.0f / (float)(1 << fs)));
}

static int16_t temp_raw(chip_state_t *chip) {
  float temperature = attr_read_float(chip->temperature_attr);
  return saturate_round((temperature - 36.53f) * 340.0f);
}

static void reset_registers(chip_state_t *chip) {
  for (int i = 0; i < REG_COUNT; ++i) {
    chip->regs[i] = 0;
  }
  chip->regs[REG_PWR_MGMT_1] = 0x40;
}

static uint8_t read_reg(chip_state_t *chip, uint8_t reg) {
  switch (reg) {
  case 0x3b:
    return high_byte(accel_raw(chip, attr_read_float(chip->accel_x_attr)));
  case 0x3c:
    return low_byte(accel_raw(chip, attr_read_float(chip->accel_x_attr)));
  case 0x3d:
    return high_byte(accel_raw(chip, attr_read_float(chip->accel_y_attr)));
  case 0x3e:
    return low_byte(accel_raw(chip, attr_read_float(chip->accel_y_attr)));
  case 0x3f:
    return high_byte(accel_raw(chip, attr_read_float(chip->accel_z_attr)));
  case 0x40:
    return low_byte(accel_raw(chip, attr_read_float(chip->accel_z_attr)));
  case 0x41:
    return high_byte(temp_raw(chip));
  case 0x42:
    return low_byte(temp_raw(chip));
  case 0x43:
    return high_byte(gyro_raw(chip, attr_read_float(chip->rotation_x_attr)));
  case 0x44:
    return low_byte(gyro_raw(chip, attr_read_float(chip->rotation_x_attr)));
  case 0x45:
    return high_byte(gyro_raw(chip, attr_read_float(chip->rotation_y_attr)));
  case 0x46:
    return low_byte(gyro_raw(chip, attr_read_float(chip->rotation_y_attr)));
  case 0x47:
    return high_byte(gyro_raw(chip, attr_read_float(chip->rotation_z_attr)));
  case 0x48:
    return low_byte(gyro_raw(chip, attr_read_float(chip->rotation_z_attr)));
  case REG_WHO_AM_I:
    return 0x68;
  default:
    return chip->regs[reg];
  }
}

static void write_reg(chip_state_t *chip, uint8_t reg, uint8_t value) {
  if (reg == REG_PWR_MGMT_1 && (value & 0x80) != 0) {
    reset_registers(chip);
    return;
  }
  chip->regs[reg] = value;
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
    chip->spi_reg = value & 0x7f;
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
  chip->accel_x_attr = attr_init_float("accelX", 0.0f);
  chip->accel_y_attr = attr_init_float("accelY", 0.0f);
  chip->accel_z_attr = attr_init_float("accelZ", 1.0f);
  chip->rotation_x_attr = attr_init_float("rotationX", 0.0f);
  chip->rotation_y_attr = attr_init_float("rotationY", 0.0f);
  chip->rotation_z_attr = attr_init_float("rotationZ", 0.0f);
  chip->temperature_attr = attr_init_float("temperatureC", 25.0f);
  chip->cs = pin_init("CS", INPUT_PULLUP);
  chip->sck = pin_init("SCK", INPUT);
  chip->sdi = pin_init("SDI", INPUT);
  chip->sdo = pin_init("SDO", OUTPUT_HIGH);

  reset_registers(chip);
  chip->spi_selected = false;
  spi_reset(chip);

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

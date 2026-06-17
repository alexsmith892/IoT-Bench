#include <zephyr/kernel.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/sys/printk.h>
#include <string.h>

static const struct spi_dt_spec bme =
	SPI_DT_SPEC_GET(DT_ALIAS(my_sensor), SPI_OP_MODE_MASTER | SPI_WORD_SET(8) | SPI_TRANSFER_MSB, 0);

static int bme_read(uint8_t reg, uint8_t *buf, size_t len)
{
	uint8_t tx[32] = {0};
	uint8_t rx[32] = {0};
	const struct spi_buf tx_buf = {.buf = tx, .len = len + 1};
	const struct spi_buf rx_buf = {.buf = rx, .len = len + 1};
	const struct spi_buf_set tx_set = {.buffers = &tx_buf, .count = 1};
	const struct spi_buf_set rx_set = {.buffers = &rx_buf, .count = 1};

	if (len + 1 > sizeof(tx)) {
		return -1;
	}
	tx[0] = reg | 0x80;
	int err = spi_transceive_dt(&bme, &tx_set, &rx_set);
	if (err != 0) {
		return err;
	}
	memcpy(buf, &rx[1], len);
	return 0;
}

static int bme_write(uint8_t reg, uint8_t value)
{
	uint8_t tx[2] = {reg & 0x7F, value};
	const struct spi_buf tx_buf = {.buf = tx, .len = sizeof(tx)};
	const struct spi_buf_set tx_set = {.buffers = &tx_buf, .count = 1};

	return spi_write_dt(&bme, &tx_set);
}

static uint16_t dig_t1;
static int16_t dig_t2, dig_t3;
static uint8_t dig_h1, dig_h3;
static int16_t dig_h2, dig_h4, dig_h5;
static int8_t dig_h6;
static int32_t t_fine;

static int read_calibration(void)
{
	uint8_t buf[26];
	int err;

	err = bme_read(0x88, buf, 26);
	if (err != 0) {
		return err;
	}
	dig_t1 = (uint16_t)((buf[1] << 8) | buf[0]);
	dig_t2 = (int16_t)((buf[3] << 8) | buf[2]);
	dig_t3 = (int16_t)((buf[5] << 8) | buf[4]);
	dig_h1 = buf[25];
	err = bme_read(0xE1, buf, 7);
	if (err != 0) {
		return err;
	}
	dig_h2 = (int16_t)((buf[1] << 8) | buf[0]);
	dig_h3 = buf[2];
	dig_h4 = (int16_t)((buf[3] << 4) | (buf[4] & 0x0F));
	dig_h5 = (int16_t)((buf[5] << 4) | (buf[4] >> 4));
	dig_h6 = (int8_t)buf[6];
	return 0;
}

static int32_t compensate_temperature(int32_t adc_t)
{
	int32_t var1 = ((((adc_t >> 3) - ((int32_t)dig_t1 << 1))) * (int32_t)dig_t2) >> 11;
	int32_t var2 = (((((adc_t >> 4) - (int32_t)dig_t1) *
			  ((adc_t >> 4) - (int32_t)dig_t1)) >> 12) * (int32_t)dig_t3) >> 14;

	t_fine = var1 + var2;
	return (t_fine * 5 + 128) >> 8;
}

static uint32_t compensate_humidity(int32_t adc_h)
{
	int32_t v = t_fine - 76800;

	v = ((((adc_h << 14) - ((int32_t)dig_h4 << 20) - ((int32_t)dig_h5 * v)) + 16384) >> 15) *
	    (((((((v * (int32_t)dig_h6) >> 10) *
		 (((v * (int32_t)dig_h3) >> 11) + 32768)) >> 10) + 2097152) *
		  (int32_t)dig_h2 + 8192) >> 14);
	v = v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)dig_h1) >> 4);
	v = v < 0 ? 0 : v;
	v = v > 419430400 ? 419430400 : v;
	return (uint32_t)(v >> 12);
}

int main(void)
{
	uint8_t raw[8];
	int err;

	if (!spi_is_ready_dt(&bme)) {
		printk("BME280 SPI not ready\n");
		return 0;
	}
	err = read_calibration();
	if (err != 0) {
		printk("BME280 SPI not found: %d\n", err);
		return 0;
	}
	(void)bme_write(0xF2, 0x01);
	(void)bme_write(0xF4, 0x27);
	while (1) {
		if (bme_read(0xF7, raw, sizeof(raw)) == 0) {
			int32_t adc_t = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) | (raw[5] >> 4);
			int32_t adc_h = ((int32_t)raw[6] << 8) | raw[7];
			int32_t temp = compensate_temperature(adc_t);
			uint32_t hum = compensate_humidity(adc_h);
			int32_t t_frac = temp % 100;
			uint32_t h_deci = (hum * 10) >> 10;
			if (t_frac < 0) {
				t_frac = -t_frac;
			}
			printk("Temperature: %d.%02d C Humidity: %u.%u %%\n",
			       temp / 100, t_frac, h_deci / 10, h_deci % 10);
		}
		k_msleep(250);
	}
	return 0;
}

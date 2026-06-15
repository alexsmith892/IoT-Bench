#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define BME280_ADDR 0x76

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

/* Separate stopped write+read transactions: the simulated bus does not
 * support repeated-start combined transfers (stated in the prompt). */
static int bme_read(uint8_t reg, uint8_t *buf, uint32_t len)
{
	if (i2c_write(i2c_dev, &reg, 1, BME280_ADDR) != 0) {
		return -1;
	}
	return i2c_read(i2c_dev, buf, len, BME280_ADDR);
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

	if (bme_read(0x88, buf, 26) != 0) {
		return -1;
	}
	dig_t1 = (uint16_t)((buf[1] << 8) | buf[0]);
	dig_t2 = (int16_t)((buf[3] << 8) | buf[2]);
	dig_t3 = (int16_t)((buf[5] << 8) | buf[4]);
	dig_h1 = buf[25];
	if (bme_read(0xE1, buf, 7) != 0) {
		return -1;
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
	return (t_fine * 5 + 128) >> 8; /* 0.01 degC */
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
	return (uint32_t)(v >> 12); /* %RH in Q22.10 */
}

int main(void)
{
	uint8_t raw[8];

	if (read_calibration() != 0) {
		printk("BME280 calibration read failed\n");
		return 0;
	}
	/* humidity oversampling x1, then temp/press oversampling x1, normal mode */
	(void)i2c_reg_write_byte(i2c_dev, BME280_ADDR, 0xF2, 0x01);
	(void)i2c_reg_write_byte(i2c_dev, BME280_ADDR, 0xF4, 0x27);

	while (1) {
		if (bme_read(0xF7, raw, sizeof(raw)) == 0) {
			int32_t adc_t = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) | (raw[5] >> 4);
			int32_t adc_h = ((int32_t)raw[6] << 8) | raw[7];
			int32_t temp = compensate_temperature(adc_t);
			uint32_t hum = compensate_humidity(adc_h);
			int32_t t_whole = temp / 100;
			int32_t t_frac = temp % 100;
			uint32_t h_deci = (hum * 10) >> 10;

			if (t_frac < 0) {
				t_frac = -t_frac;
			}
			printk("Temperature: %d.%02d C Humidity: %u.%u %%\n",
			       t_whole, t_frac, h_deci / 10, h_deci % 10);
		}
		k_msleep(200);
	}
	return 0;
}

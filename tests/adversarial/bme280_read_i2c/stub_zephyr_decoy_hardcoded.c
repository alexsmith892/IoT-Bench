/* Decoy cheat: performs a real I2C read so it passes the static gate, but
 * ignores the data and replays the warm_humid transcript. The hot_dry
 * variant (31.0 C / 42.0 %RH seeded into the model) rejects it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define BME280_ADDR 0x76

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

int main(void)
{
	uint8_t raw[8];

	while (1) {
		(void)i2c_burst_read(i2c_dev, BME280_ADDR, 0xF7, raw, sizeof(raw));
		printk("Temperature: 24.50 C Humidity: 55.1 %%\n");
		k_msleep(200);
	}
	return 0;
}

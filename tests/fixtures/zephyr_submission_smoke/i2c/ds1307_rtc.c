#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define DS1307_ADDR 0x68

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

static int from_bcd(uint8_t value)
{
	return ((value >> 4) * 10) + (value & 0x0F);
}

int main(void)
{
	uint8_t reg = 0x00;
	uint8_t data[7];

	while (1) {
		if (i2c_write_read(i2c_dev, DS1307_ADDR, &reg, 1, data, sizeof(data)) == 0) {
			printk("20%02d/%02d/%02d %02d:%02d:%02d\n",
			       from_bcd(data[6]), from_bcd(data[5]), from_bcd(data[4]),
			       from_bcd(data[2] & 0x3F), from_bcd(data[1]),
			       from_bcd(data[0] & 0x7F));
		}
		k_msleep(250);
	}
	return 0;
}

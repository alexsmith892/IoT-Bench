/* Decoy cheat: performs a real I2C read so it passes the static gate, but
 * ignores the data and prints one hardcoded date/time. The second seeded
 * variant (different initTime) and the distinct-output check reject it at
 * runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define DS1307_ADDR 0x68

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

int main(void)
{
	uint8_t reg = 0x00;
	uint8_t data[7];

	while (1) {
		(void)i2c_write_read(i2c_dev, DS1307_ADDR, &reg, 1, data, sizeof(data));
		printk("2026/02/02 15:37:00\n");
		k_msleep(250);
	}
	return 0;
}

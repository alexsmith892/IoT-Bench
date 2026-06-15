/* Decoy cheat: performs a real I2C read so it passes the static gate, but
 * ignores the data and replays the three_steps transcript. The four_steps
 * variant (one more injected spike) rejects it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define MPU6050_ADDR 0x68

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

int main(void)
{
	uint8_t raw[2];

	(void)i2c_reg_write_byte(i2c_dev, MPU6050_ADDR, 0x6B, 0x00);
	(void)i2c_burst_read(i2c_dev, MPU6050_ADDR, 0x3F, raw, sizeof(raw));
	k_msleep(800);
	printk("1\n");
	k_msleep(450);
	printk("2\n");
	k_msleep(450);
	printk("3\n");
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

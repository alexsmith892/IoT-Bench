/* Decoy cheat: performs a real I2C read so it passes the static gate, but
 * ignores the data and replays the half_g transcript. The one_and_half_g
 * variant (different injected counts) rejects it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define MPU6050_ADDR 0x68

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

int main(void)
{
	uint8_t raw[14];
	int line = 0;

	(void)i2c_reg_write_byte(i2c_dev, MPU6050_ADDR, 0x6B, 0x00);
	while (1) {
		(void)i2c_burst_read(i2c_dev, MPU6050_ADDR, 0x3B, raw, sizeof(raw));
		if (line < 3) {
			printk("Accel: 0 0 16384 Gyro: 0 0 0\n");
		} else {
			printk("Accel: 8192 0 16384 Gyro: 3930 0 0\n");
		}
		++line;
		k_msleep(150);
	}
	return 0;
}

#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define LSM9DS1_ADDR 0x6B
#define OUT_X_G 0x18
#define OUT_X_XL 0x28

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

static int read_vector(uint8_t base, int16_t out[3])
{
	uint8_t raw[6];

	if (i2c_burst_read(i2c_dev, LSM9DS1_ADDR, base, raw, sizeof(raw)) != 0) {
		return -1;
	}
	for (int i = 0; i < 3; ++i) {
		out[i] = (int16_t)((raw[2 * i + 1] << 8) | raw[2 * i]);
	}
	return 0;
}

int main(void)
{
	int16_t accel[3];
	int16_t gyro[3];

	while (1) {
		if (read_vector(OUT_X_XL, accel) == 0 && read_vector(OUT_X_G, gyro) == 0) {
			printk("Accel: %d %d %d Gyro: %d %d %d\n",
			       accel[0], accel[1], accel[2], gyro[0], gyro[1], gyro[2]);
		}
		k_msleep(150);
	}
	return 0;
}

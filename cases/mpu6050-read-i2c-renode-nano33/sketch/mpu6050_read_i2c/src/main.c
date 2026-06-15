#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define MPU6050_ADDR 0x68
#define PWR_MGMT_1 0x6B
#define ACCEL_XOUT_H 0x3B

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

int main(void)
{
	uint8_t raw[14];

	/* Wake from sleep: clear the SLEEP bit (power-on default 0x40). */
	(void)i2c_reg_write_byte(i2c_dev, MPU6050_ADDR, PWR_MGMT_1, 0x00);

	while (1) {
		if (i2c_burst_read(i2c_dev, MPU6050_ADDR, ACCEL_XOUT_H, raw, sizeof(raw)) == 0) {
			int16_t ax = (int16_t)((raw[0] << 8) | raw[1]);
			int16_t ay = (int16_t)((raw[2] << 8) | raw[3]);
			int16_t az = (int16_t)((raw[4] << 8) | raw[5]);
			int16_t gx = (int16_t)((raw[8] << 8) | raw[9]);
			int16_t gy = (int16_t)((raw[10] << 8) | raw[11]);
			int16_t gz = (int16_t)((raw[12] << 8) | raw[13]);

			printk("Accel: %d %d %d Gyro: %d %d %d\n", ax, ay, az, gx, gy, gz);
		}
		k_msleep(150);
	}
	return 0;
}

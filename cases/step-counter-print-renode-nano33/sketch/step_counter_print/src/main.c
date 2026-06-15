#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/printk.h>

#define MPU6050_ADDR 0x68
#define PWR_MGMT_1 0x6B
#define ACCEL_ZOUT_H 0x3F
#define STEP_THRESHOLD 23700 /* ~1.45 g at 16384 counts/g */

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

int main(void)
{
	uint8_t raw[2];
	int steps = 0;
	bool above = false;

	(void)i2c_reg_write_byte(i2c_dev, MPU6050_ADDR, PWR_MGMT_1, 0x00);
	while (1) {
		if (i2c_burst_read(i2c_dev, MPU6050_ADDR, ACCEL_ZOUT_H, raw, sizeof(raw)) == 0) {
			int16_t az = (int16_t)((raw[0] << 8) | raw[1]);

			if (az > STEP_THRESHOLD && !above) {
				above = true;
				printk("%d\n", ++steps);
			} else if (az <= STEP_THRESHOLD) {
				above = false;
			}
		}
		k_msleep(40);
	}
	return 0;
}

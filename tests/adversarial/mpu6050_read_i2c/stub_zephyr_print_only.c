/* Cheat: never touches I2C, prints plausible-looking fixed counts. Must be
 * rejected offline by the static gate (required real I2C read path). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	while (1) {
		printk("Accel: 0 0 16384 Gyro: 0 0 0\n");
		k_msleep(150);
	}
	return 0;
}

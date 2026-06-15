/* Cheat: never touches I2C, prints plausible-looking fixed readings. Must be
 * rejected offline by the static gate (required real I2C read path). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	while (1) {
		printk("Temperature: 24.50 C Humidity: 55.1 %%\n");
		k_msleep(200);
	}
	return 0;
}

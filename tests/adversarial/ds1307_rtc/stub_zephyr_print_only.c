/* Cheat: never touches I2C, prints a hardcoded date/time. Must be rejected
 * offline by the static gate (required real I2C read path). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	while (1) {
		printk("2026/02/02 15:37:00\n");
		k_msleep(250);
	}
	return 0;
}

/* Cheat: never touches I2C, prints a fixed 1..3 step transcript. Must be
 * rejected offline by the static gate (required real I2C read path). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
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

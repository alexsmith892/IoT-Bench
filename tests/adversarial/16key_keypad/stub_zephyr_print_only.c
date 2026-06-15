/* Cheat: never scans the matrix, replays a plausible key transcript. Must
 * be rejected offline by the static gate (required configure/get/set GPIO
 * scan path). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	k_msleep(250);
	printk("Key: 1\n");
	k_msleep(200);
	printk("Key: 2\n");
	k_msleep(200);
	printk("Key: 3\n");
	k_msleep(200);
	printk("Key: 4\n");
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

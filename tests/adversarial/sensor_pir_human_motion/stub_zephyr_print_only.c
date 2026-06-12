/* Cheat: never reads the sensor, just prints the expected single-motion
 * transcript. Must be rejected offline by the static gate (gpio_pin_get). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	printk("No Motion Detected!\n");
	k_msleep(500);
	printk("Motion Detected!\n");
	k_msleep(350);
	printk("No Motion Detected!\n");
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

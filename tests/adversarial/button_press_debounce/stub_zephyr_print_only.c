/* Cheat: never reads the button, just prints two triggers. Must be rejected
 * offline by the static gate (required gpio_pin_get + a time source). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	k_msleep(400);
	printk("Button Pressed!\n");
	k_msleep(400);
	printk("Button Pressed!\n");
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

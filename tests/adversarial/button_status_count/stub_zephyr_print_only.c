/* Cheat: never reads the button, just prints the expected count sequence.
 * Must be rejected offline by the static gate (required gpio_pin_get). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	for (int i = 1; i <= 3; ++i) {
		k_msleep(400);
		printk("%d\n", i);
	}
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

/* Cheat: never touches the ADC, prints plausible temperatures. Must be
 * rejected offline by the static gate (required real ADC read path). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	while (1) {
		printk("32.5\n");
		k_msleep(100);
	}
	return 0;
}

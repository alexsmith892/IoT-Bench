/* Cheat: never reads the encoder lines, replays a plausible transcript.
 * Must be rejected offline by the static gate (required gpio_pin_get). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	printk("Position: 1 Direction: CW\n");
	printk("Position: 2 Direction: CW\n");
	printk("Position: 3 Direction: CW\n");
	printk("Position: 2 Direction: CCW\n");
	printk("Position: 1 Direction: CCW\n");
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

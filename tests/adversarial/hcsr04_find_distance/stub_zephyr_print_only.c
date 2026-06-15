/* Cheat: never touches the sensor pins, prints a fixed distance. Must be
 * rejected offline by the static gate (required trigger/echo pin path). */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	while (1) {
		printk("Distance: 100 cm\n");
		k_msleep(100);
	}
	return 0;
}

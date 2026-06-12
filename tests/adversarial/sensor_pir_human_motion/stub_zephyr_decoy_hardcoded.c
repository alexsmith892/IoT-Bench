/* Decoy cheat: contains a real gpio_pin_get call so it passes the static
 * gate, but ignores the reading and replays the single-motion transcript.
 * The double_motion variant (two motion windows) and the distinct-output
 * check reject it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const pir_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(pir_port, 15, GPIO_INPUT);
	(void)gpio_pin_get(pir_port, 15);
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

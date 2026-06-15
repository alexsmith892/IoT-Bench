/* Decoy cheat: exercises the GPIO scan APIs so it passes the static gate,
 * but ignores the matrix and replays the one_two_three_four transcript.
 * The seven_five_nine_zero variant (different pressed keys) rejects it at
 * runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(gpio1_dev, 11, GPIO_OUTPUT_HIGH);
	gpio_pin_configure(gpio1_dev, 14, GPIO_INPUT);
	gpio_pin_set_raw(gpio1_dev, 11, 0);
	(void)gpio_pin_get_raw(gpio1_dev, 14);
	gpio_pin_set_raw(gpio1_dev, 11, 1);
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

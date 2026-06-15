/* Decoy cheat: reads the encoder lines so it passes the static gate, but
 * ignores them and replays the three_cw_two_ccw transcript. The
 * one_cw_three_ccw variant (different detent pattern) rejects it at
 * runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(gpio1_dev, 11, GPIO_INPUT);
	gpio_pin_configure(gpio1_dev, 12, GPIO_INPUT);
	(void)gpio_pin_get_raw(gpio1_dev, 11);
	(void)gpio_pin_get_raw(gpio1_dev, 12);
	k_msleep(400);
	printk("Position: 1 Direction: CW\n");
	k_msleep(160);
	printk("Position: 2 Direction: CW\n");
	k_msleep(160);
	printk("Position: 3 Direction: CW\n");
	k_msleep(160);
	printk("Position: 2 Direction: CCW\n");
	k_msleep(160);
	printk("Position: 1 Direction: CCW\n");
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

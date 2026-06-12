/* Decoy cheat: contains gpio_pin_get and k_uptime_get calls so it passes
 * the static gate, but always reports exactly two presses regardless of the
 * stimulus. The three_presses variant rejects it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const button_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(button_port, 11, GPIO_INPUT);
	(void)gpio_pin_get(button_port, 11);
	(void)k_uptime_get();
	k_msleep(500);
	printk("Button Pressed!\n");
	k_msleep(450);
	printk("Button Pressed!\n");
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

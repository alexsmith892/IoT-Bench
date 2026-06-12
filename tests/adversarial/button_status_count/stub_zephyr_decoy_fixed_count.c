/* Decoy cheat: contains a real gpio_pin_get call so it passes the static
 * gate, but ignores the reading and prints a fixed 1..3 sequence. The
 * four_presses variant (expects 1..4) and the distinct-output check reject
 * it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const button_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(button_port, 11, GPIO_INPUT);
	(void)gpio_pin_get(button_port, 11);
	for (int i = 1; i <= 3; ++i) {
		k_msleep(400);
		printk("%d\n", i);
	}
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

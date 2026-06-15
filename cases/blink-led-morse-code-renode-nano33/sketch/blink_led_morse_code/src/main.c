#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const led_port = DEVICE_DT_GET(DT_NODELABEL(gpio0));

static void set_led_for_units(int level, int units)
{
	gpio_pin_set(led_port, 24, level);
	k_msleep(200 * units);
}

int main(void)
{
	const int pattern[] = {1, 1, 1, 3, 3, 3, 1, 1, 1};

	gpio_pin_configure(led_port, 24, GPIO_OUTPUT_LOW);
	while (1) {
		for (int i = 0; i < 9; ++i) {
			set_led_for_units(1, pattern[i]);
			if (i < 8) {
				set_led_for_units(0, (i == 2 || i == 5) ? 3 : 1);
			}
		}
		set_led_for_units(0, 7);
	}
	return 0;
}

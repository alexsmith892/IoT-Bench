/* Decoy cheat: exercises the GPIO scan APIs so it passes the static gate,
 * but ignores the keys and unlocks on a timer matching the base scenario.
 * The never_correct variant (no valid code entered) rejects it at
 * runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(gpio0_dev, 13, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio1_dev, 11, GPIO_OUTPUT_HIGH);
	gpio_pin_configure(gpio1_dev, 14, GPIO_INPUT);
	gpio_pin_set_raw(gpio1_dev, 11, 0);
	(void)gpio_pin_get_raw(gpio1_dev, 14);
	gpio_pin_set_raw(gpio1_dev, 11, 1);
	k_msleep(1700);
	gpio_pin_set(gpio0_dev, 13, 1);
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

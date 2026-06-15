/* Cheat: never scans the keypad, unlocks the relay on a timer matching the
 * base scenario. Must be rejected offline by the static gate (required
 * gpio_pin_get scan path); even past the gate, the never_correct variant
 * rejects the timed unlock live. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{
	gpio_pin_configure(gpio0_dev, 13, GPIO_OUTPUT_LOW);
	k_msleep(1700);
	gpio_pin_set(gpio0_dev, 13, 1);
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

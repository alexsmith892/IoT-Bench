/* Cheat: never reads the ADC, toggles the LED on the base variant's
 * schedule. Must be rejected offline by the static gate (required ADC read
 * path); even past the gate, the dark_then_bright variant rejects the
 * fixed schedule live. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{
	gpio_pin_configure(gpio0_dev, 24, GPIO_OUTPUT_LOW);
	k_msleep(600);
	gpio_pin_set(gpio0_dev, 24, 1);
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

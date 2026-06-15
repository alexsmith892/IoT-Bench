#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const input_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));
static const struct device *const relay_port = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{
	int last = 0;
	int relay = 0;

	gpio_pin_configure(input_port, 15, GPIO_INPUT);
	gpio_pin_configure(relay_port, 16, GPIO_OUTPUT_LOW);

	while (1) {
		int current = gpio_pin_get(input_port, 15);
		if (current && !last) {
			relay = !relay;
			gpio_pin_set(relay_port, 16, relay);
		}
		last = current;
		k_msleep(5);
	}
	return 0;
}

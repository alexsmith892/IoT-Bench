#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const led1_port = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const led2_port = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{
	int led1 = 0;
	int led2 = 0;
	int64_t last_led1_ms;
	int64_t last_led2_ms;

	gpio_pin_configure(led1_port, 24, GPIO_OUTPUT_LOW);
	gpio_pin_configure(led2_port, 16, GPIO_OUTPUT_LOW);
	last_led1_ms = k_uptime_get();
	last_led2_ms = last_led1_ms;
	while (1) {
		int64_t now = k_uptime_get();

		if (now - last_led1_ms >= 500) {
			last_led1_ms += 500;
			led1 = !led1;
			gpio_pin_set(led1_port, 24, led1);
		}
		if (now - last_led2_ms >= 250) {
			last_led2_ms += 250;
			led2 = !led2;
			gpio_pin_set(led2_port, 16, led2);
		}
		k_yield();
	}
	return 0;
}

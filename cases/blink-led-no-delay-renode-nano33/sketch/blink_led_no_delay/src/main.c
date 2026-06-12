#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const led_port = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{
	int level = 0;
	int64_t last_toggle_ms;

	gpio_pin_configure(led_port, 24, GPIO_OUTPUT_LOW);
	last_toggle_ms = k_uptime_get();
	while (1) {
		int64_t now = k_uptime_get();

		if (now - last_toggle_ms >= 500) {
			last_toggle_ms += 500;
			level = !level;
			gpio_pin_set(led_port, 24, level);
		}
		k_yield();
	}
	return 0;
}

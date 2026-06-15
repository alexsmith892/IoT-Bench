#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const button_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));
static const struct device *const buzzer_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));

#define DEBOUNCE_MS 30

int main(void)
{
	int stable = 0;
	int last_reading = 0;
	int64_t changed_at_ms;

	gpio_pin_configure(button_port, 11, GPIO_INPUT);
	gpio_pin_configure(buzzer_port, 12, GPIO_OUTPUT_LOW);
	changed_at_ms = k_uptime_get();
	while (1) {
		int reading = gpio_pin_get(button_port, 11);
		int64_t now = k_uptime_get();

		if (reading != last_reading) {
			last_reading = reading;
			changed_at_ms = now;
		}
		if (now - changed_at_ms >= DEBOUNCE_MS && stable != reading) {
			stable = reading;
		}
		gpio_pin_set(buzzer_port, 12, stable);
		k_msleep(1);
	}
	return 0;
}

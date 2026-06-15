#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const button_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));
static const struct device *const led_port = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const buzzer_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));

static int64_t half_period_ms(int mode)
{
	switch (mode) {
	case 1:
		return 500;
	case 2:
		return 250;
	case 3:
		return 125;
	default:
		return 0;
	}
}

int main(void)
{
	int mode = 0;
	int last_button = 0;
	int led_state = 0;
	int buzzer_state = 0;
	int64_t last_led_toggle = k_uptime_get();
	int64_t last_buzzer_toggle = 0;
	int64_t buzzer_until = 0;

	gpio_pin_configure(button_port, 11, GPIO_INPUT);
	gpio_pin_configure(led_port, 16, GPIO_OUTPUT_LOW);
	gpio_pin_configure(buzzer_port, 12, GPIO_OUTPUT_LOW);

	while (1) {
		int64_t now = k_uptime_get();
		int button = gpio_pin_get(button_port, 11);

		if (button && !last_button) {
			mode = (mode + 1) % 4;
			led_state = 0;
			last_led_toggle = now;
			gpio_pin_set(led_port, 16, led_state);
			buzzer_until = now + 80;
			last_buzzer_toggle = now;
		}
		last_button = button;

		int64_t half = half_period_ms(mode);
		if (half == 0) {
			led_state = 0;
			gpio_pin_set(led_port, 16, 0);
		} else if (now - last_led_toggle >= half) {
			last_led_toggle += half;
			led_state = !led_state;
			gpio_pin_set(led_port, 16, led_state);
		}

		if (now < buzzer_until) {
			if (now - last_buzzer_toggle >= 1) {
				last_buzzer_toggle = now;
				buzzer_state = !buzzer_state;
				gpio_pin_set(buzzer_port, 12, buzzer_state);
			}
		} else if (buzzer_state) {
			buzzer_state = 0;
			gpio_pin_set(buzzer_port, 12, 0);
		}

		k_msleep(1);
	}
	return 0;
}

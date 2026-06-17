/* Cheat-adjacent failure: emits active PWM but never performs the 50-step
 * breathing ramp. The pwm_breathing oracle rejects it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const led_port = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{
	gpio_pin_configure(led_port, 24, GPIO_OUTPUT_LOW);
	while (1) {
		gpio_pin_set(led_port, 24, 1);
		k_busy_wait(1000);
		gpio_pin_set(led_port, 24, 0);
		k_busy_wait(1000);
	}
	return 0;
}

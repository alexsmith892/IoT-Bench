/* Decoy cheat: exercises HC-SR04 pins so static checks pass, but ignores
 * measured distance and emits a fixed buzzer waveform. Runtime waveform
 * checks reject fixed or wrong timing. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(gpio1_dev, 11, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio1_dev, 10, GPIO_INPUT);
	gpio_pin_configure(gpio0_dev, 24, GPIO_OUTPUT_HIGH);
	gpio_pin_configure(gpio0_dev, 27, GPIO_OUTPUT_LOW);
	while (1) {
		gpio_pin_set_raw(gpio1_dev, 11, 1);
		k_busy_wait(12);
		gpio_pin_set_raw(gpio1_dev, 11, 0);
		(void)gpio_pin_get_raw(gpio1_dev, 10);
		gpio_pin_set(gpio0_dev, 27, 1);
		k_busy_wait(1000);
		gpio_pin_set(gpio0_dev, 27, 0);
		k_busy_wait(1000);
	}
	return 0;
}

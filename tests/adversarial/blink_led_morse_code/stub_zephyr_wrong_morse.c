/* Cheat-adjacent failure: drives the LED but emits a regular blink pattern
 * instead of SOS. The morse_sos waveform oracle rejects it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const led_port = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{
	gpio_pin_configure(led_port, 24, GPIO_OUTPUT_LOW);
	while (1) {
		gpio_pin_toggle(led_port, 24);
		k_msleep(300);
	}
	return 0;
}

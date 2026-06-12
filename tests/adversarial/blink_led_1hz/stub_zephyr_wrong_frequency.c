/* Cheat-adjacent failure: blinks at 2 Hz instead of 1 Hz. There is no
 * static gate on this task; the waveform_frequency oracle rejects it at
 * runtime (live-verified BF). */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const led_port = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{
	gpio_pin_configure(led_port, 24, GPIO_OUTPUT_LOW);
	while (1) {
		gpio_pin_toggle(led_port, 24);
		k_msleep(250);
	}
	return 0;
}

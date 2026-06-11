#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const pir_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	int last_state = -1;

	gpio_pin_configure(pir_port, 15, GPIO_INPUT);
	while (1) {
		int state = gpio_pin_get(pir_port, 15);

		if (state != last_state) {
			printk("%s\n", state ? "Motion Detected!" : "No Motion Detected!");
			last_state = state;
		}
		k_msleep(10);
	}
	return 0;
}

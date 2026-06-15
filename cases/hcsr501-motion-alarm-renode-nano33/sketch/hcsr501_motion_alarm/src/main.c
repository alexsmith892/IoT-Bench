#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const input_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));
static const struct device *const output_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(input_port, 15, GPIO_INPUT);
	gpio_pin_configure(output_port, 12, GPIO_OUTPUT_LOW);

	while (1) {
		gpio_pin_set(output_port, 12, gpio_pin_get(input_port, 15));
		k_msleep(5);
	}
	return 0;
}

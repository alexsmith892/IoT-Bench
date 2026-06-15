#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const button_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));
static const struct device *const buzzer_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(button_port, 11, GPIO_INPUT);
	gpio_pin_configure(buzzer_port, 12, GPIO_OUTPUT_LOW);
	while (1) {
		gpio_pin_set(buzzer_port, 12, gpio_pin_get(button_port, 11));
		k_msleep(1);
	}
	return 0;
}

#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const button_port = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	int was_pressed = 0;

	gpio_pin_configure(button_port, 11, GPIO_INPUT);
	while (1) {
		int pressed = gpio_pin_get(button_port, 11);

		if (pressed && !was_pressed) {
			printk("Button Pressed!\n");
		}
		was_pressed = pressed;
		k_msleep(5);
	}
	return 0;
}

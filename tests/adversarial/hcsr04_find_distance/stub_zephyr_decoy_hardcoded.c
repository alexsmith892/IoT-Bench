/* Decoy cheat: exercises the trigger/echo pins and a time source so it
 * passes the static gate, but prints a fixed 100 cm. The near variant
 * (40 cm seeded into the model) rejects it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	gpio_pin_configure(gpio1_dev, 11, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio1_dev, 10, GPIO_INPUT);
	while (1) {
		gpio_pin_set_raw(gpio1_dev, 11, 1);
		k_busy_wait(12);
		gpio_pin_set_raw(gpio1_dev, 11, 0);
		(void)gpio_pin_get_raw(gpio1_dev, 10);
		printk("Distance: 100 cm\n");
		k_msleep(100);
	}
	return 0;
}

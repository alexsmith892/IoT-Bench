#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

#define CLK_PIN 11
#define DT_PIN 12

static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

/* quarter-step direction per (previous state, new state), state = CLK<<1|DT */
static const int8_t quarter[4][4] = {
	/* from 00 */ {0, -1, 1, 0},
	/* from 01 */ {1, 0, 0, -1},
	/* from 10 */ {-1, 0, 0, 1},
	/* from 11 */ {0, 1, -1, 0},
};

int main(void)
{
	int position = 0;
	int quarters = 0;

	gpio_pin_configure(gpio1_dev, CLK_PIN, GPIO_INPUT);
	gpio_pin_configure(gpio1_dev, DT_PIN, GPIO_INPUT);

	int prev = (gpio_pin_get_raw(gpio1_dev, CLK_PIN) << 1) | gpio_pin_get_raw(gpio1_dev, DT_PIN);

	while (1) {
		int state = (gpio_pin_get_raw(gpio1_dev, CLK_PIN) << 1) |
			    gpio_pin_get_raw(gpio1_dev, DT_PIN);

		if (state != prev) {
			quarters += quarter[prev][state];
			prev = state;
			if (state == 3) {
				if (quarters >= 4) {
					position++;
					printk("Position: %d Direction: CW\n", position);
				} else if (quarters <= -4) {
					position--;
					printk("Position: %d Direction: CCW\n", position);
				}
				quarters = 0;
			}
		}
		k_msleep(1);
	}
	return 0;
}

#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

struct line {
	const struct device *port;
	int pin;
};

static const struct line rows[4] = {
	{NULL, 11}, {NULL, 12}, {NULL, 15}, {NULL, 13},
};
static const struct line cols[4] = {
	{NULL, 14}, {NULL, 23}, {NULL, 21}, {NULL, 27},
};
static const char legend[4][4] = {
	{'1', '2', '3', 'A'},
	{'4', '5', '6', 'B'},
	{'7', '8', '9', 'C'},
	{'*', '0', '#', 'D'},
};

int main(void)
{
	struct line row_lines[4], col_lines[4];
	bool held[4][4] = {0};

	for (int r = 0; r < 4; ++r) {
		row_lines[r] = rows[r];
		row_lines[r].port = gpio1_dev;
		gpio_pin_configure(row_lines[r].port, row_lines[r].pin, GPIO_OUTPUT_HIGH);
	}
	for (int c = 0; c < 4; ++c) {
		col_lines[c] = cols[c];
		col_lines[c].port = (c == 0) ? gpio1_dev : gpio0_dev;
		gpio_pin_configure(col_lines[c].port, col_lines[c].pin, GPIO_INPUT);
	}

	while (1) {
		for (int r = 0; r < 4; ++r) {
			gpio_pin_set_raw(row_lines[r].port, row_lines[r].pin, 0);
			k_msleep(1);
			for (int c = 0; c < 4; ++c) {
				bool pressed = gpio_pin_get_raw(col_lines[c].port, col_lines[c].pin) == 0;

				if (pressed && !held[r][c]) {
					printk("Key: %c\n", legend[r][c]);
				}
				held[r][c] = pressed;
			}
			gpio_pin_set_raw(row_lines[r].port, row_lines[r].pin, 1);
		}
		k_msleep(5);
	}
	return 0;
}

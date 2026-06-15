#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

#define RELAY_PIN 13

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

static const int row_pins[2] = {11, 12};
static const char legend[2][3] = {{'1', '2', '3'}, {'4', '5', '6'}};

struct line {
	const struct device *port;
	int pin;
};

int main(void)
{
	const struct line cols[3] = {
		{gpio1_dev, 14}, {gpio0_dev, 23}, {gpio0_dev, 21},
	};
	bool held[2][3] = {0};
	char entered[5] = {0};
	int count = 0;
	bool unlocked = false;

	gpio_pin_configure(gpio0_dev, RELAY_PIN, GPIO_OUTPUT_LOW);
	for (int r = 0; r < 2; ++r) {
		gpio_pin_configure(gpio1_dev, row_pins[r], GPIO_OUTPUT_HIGH);
	}
	for (int c = 0; c < 3; ++c) {
		gpio_pin_configure(cols[c].port, cols[c].pin, GPIO_INPUT);
	}

	while (1) {
		for (int r = 0; r < 2; ++r) {
			gpio_pin_set_raw(gpio1_dev, row_pins[r], 0);
			k_msleep(1);
			for (int c = 0; c < 3; ++c) {
				bool pressed = gpio_pin_get_raw(cols[c].port, cols[c].pin) == 0;

				if (pressed && !held[r][c] && !unlocked && count < 4) {
					entered[count++] = legend[r][c];
				}
				held[r][c] = pressed;
			}
			gpio_pin_set_raw(gpio1_dev, row_pins[r], 1);
		}
		if (count == 4) {
			if (entered[0] == '1' && entered[1] == '2' &&
			    entered[2] == '3' && entered[3] == '4') {
				unlocked = true;
				gpio_pin_set(gpio0_dev, RELAY_PIN, 1);
			}
			count = 0;
		}
		k_msleep(5);
	}
	return 0;
}

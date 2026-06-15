#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <stdio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));


#define LED_PIN 24
#define CARRIER_US 2000
#define STEP_PERIODS 5 /* 5 x 2 ms carrier = one 10 ms duty step */

static void pwm_step(int duty_percent)
{
	int on_us = CARRIER_US * duty_percent / 100;

	for (int i = 0; i < STEP_PERIODS; ++i) {
		if (on_us > 0) {
			gpio_pin_set(gpio0_dev, LED_PIN, 1);
			k_busy_wait(on_us);
		}
		if (on_us < CARRIER_US) {
			gpio_pin_set(gpio0_dev, LED_PIN, 0);
			k_busy_wait(CARRIER_US - on_us);
		}
	}
}

int main(void)
{
	gpio_pin_configure(gpio0_dev, LED_PIN, GPIO_OUTPUT_LOW);
	while (1) {
		for (int level = 1; level <= 50; ++level) {
			pwm_step(level * 2);
		}
		for (int level = 50; level >= 1; --level) {
			pwm_step(level * 2);
		}
	}
	return 0;
}

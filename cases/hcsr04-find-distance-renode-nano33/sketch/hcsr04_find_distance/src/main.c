#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <stdio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

#include <zephyr/sys/printk.h>

#define TRIG_PIN 11
#define ECHO_PIN 10

/* One HC-SR04 measurement: 10 us trigger pulse, then time the echo pulse
 * (58 us/cm). Returns centimeters or -1 on timeout. */
static int hcsr04_measure(void)
{
	uint32_t start, deadline;

	gpio_pin_set_raw(gpio1_dev, TRIG_PIN, 1);
	k_busy_wait(12);
	gpio_pin_set_raw(gpio1_dev, TRIG_PIN, 0);

	deadline = k_cycle_get_32() + k_us_to_cyc_ceil32(30000);
	while (gpio_pin_get_raw(gpio1_dev, ECHO_PIN) == 0) {
		if ((int32_t)(k_cycle_get_32() - deadline) > 0) {
			return -1;
		}
	}
	start = k_cycle_get_32();
	while (gpio_pin_get_raw(gpio1_dev, ECHO_PIN) == 1) {
		if ((int32_t)(k_cycle_get_32() - deadline) > 0) {
			return -1;
		}
	}
	return (int)(k_cyc_to_us_floor32(k_cycle_get_32() - start) / 58);
}


int main(void)
{
	gpio_pin_configure(gpio1_dev, TRIG_PIN, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio1_dev, ECHO_PIN, GPIO_INPUT);

	while (1) {
		int cm = hcsr04_measure();

		if (cm >= 0) {
			printk("Distance: %d cm\n", cm);
		}
		k_msleep(100);
	}
	return 0;
}

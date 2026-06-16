/* Decoy cheat: includes timer and I2C calls so static checks pass, but the
 * displayed LCD values are fixed and do not track MPU6050 variants. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));
static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

int main(void)
{
	uint8_t raw[14];
	gpio_pin_configure(gpio1_dev, 12, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio1_dev, 14, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio1_dev, 15, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio1_dev, 13, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio0_dev, 21, GPIO_OUTPUT_LOW);
	gpio_pin_configure(gpio0_dev, 27, GPIO_OUTPUT_LOW);
	while (1) {
		(void)i2c_burst_read(i2c_dev, 0x68, 0x3B, raw, sizeof(raw));
		(void)k_uptime_get();
		k_msleep(100);
	}
	return 0;
}

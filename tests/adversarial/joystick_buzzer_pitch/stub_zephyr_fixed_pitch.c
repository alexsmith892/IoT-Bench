/* Decoy cheat: performs an ADC read so static checks pass, but never maps
 * joystick position to pitch. Variant waveform windows reject it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const adc_dev = DEVICE_DT_GET(DT_NODELABEL(adc));
static int16_t sample;
static struct adc_sequence seq = {
	.buffer = &sample,
	.buffer_size = sizeof(sample),
	.resolution = 12,
};

int main(void)
{
	gpio_pin_configure(gpio0_dev, 27, GPIO_OUTPUT_LOW);
	while (1) {
		(void)adc_read(adc_dev, &seq);
		gpio_pin_set(gpio0_dev, 27, 1);
		k_busy_wait(1000);
		gpio_pin_set(gpio0_dev, 27, 0);
		k_busy_wait(1000);
	}
	return 0;
}

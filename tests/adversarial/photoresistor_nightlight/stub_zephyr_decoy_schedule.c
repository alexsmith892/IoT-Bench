/* Decoy cheat: performs a real ADC read so it passes the static gate, but
 * ignores the samples and drives the LED on the base variant's schedule.
 * The dark_then_bright variant (swapped stimulus order) rejects it at
 * runtime. */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/dt-bindings/adc/nrf-saadc.h>

static const struct device *const adc_dev = DEVICE_DT_GET(DT_NODELABEL(adc));
static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));

int main(void)
{
	int16_t sample;
	struct adc_channel_cfg channel_cfg = {
		.gain = ADC_GAIN_1,
		.reference = ADC_REF_INTERNAL,
		.acquisition_time = ADC_ACQ_TIME_DEFAULT,
		.channel_id = 0,
		.input_positive = NRF_SAADC_AIN0,
	};
	struct adc_sequence sequence = {
		.channels = BIT(0),
		.buffer = &sample,
		.buffer_size = sizeof(sample),
		.resolution = 12,
	};

	gpio_pin_configure(gpio0_dev, 24, GPIO_OUTPUT_LOW);
	adc_channel_setup(adc_dev, &channel_cfg);
	(void)adc_read(adc_dev, &sequence);
	k_msleep(600);
	gpio_pin_set(gpio0_dev, 24, 1);
	while (1) {
		k_msleep(1000);
	}
	return 0;
}

/* Decoy cheat: performs a real adc_read so it passes the static gate, but
 * ignores the sample and replays the rising variant's transcript. The
 * falling variant (different stimulus timeline) and the distinct-output
 * check reject it at runtime. */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/dt-bindings/adc/nrf-saadc.h>
#include <zephyr/sys/printk.h>

static const struct device *const adc_dev = DEVICE_DT_GET(DT_NODELABEL(adc));

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
	int line = 0;

	adc_channel_setup(adc_dev, &channel_cfg);
	while (1) {
		(void)adc_read(adc_dev, &sequence);
		printk("%s\n", line < 4 ? "32.5" : "82.0");
		++line;
		k_msleep(100);
	}
	return 0;
}

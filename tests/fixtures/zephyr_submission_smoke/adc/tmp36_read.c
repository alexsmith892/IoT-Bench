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

	adc_channel_setup(adc_dev, &channel_cfg);
	while (1) {
		if (adc_read(adc_dev, &sequence) == 0) {
			float voltage = sample * (3.3f / 4095.0f);
			float celsius = (voltage - 0.5f) * 100.0f;
			printk("%.1f\n", (double)celsius);
		}
		k_msleep(100);
	}
	return 0;
}

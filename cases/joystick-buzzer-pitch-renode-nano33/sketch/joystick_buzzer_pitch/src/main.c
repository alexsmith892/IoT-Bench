#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <stdio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/dt-bindings/adc/nrf-saadc.h>

static const struct device *const adc_dev = DEVICE_DT_GET(DT_NODELABEL(adc));
static int16_t adc_sample;
static struct adc_sequence adc_seq;

static int adc_setup(int channel, int input)
{
	struct adc_channel_cfg cfg = {
		.gain = ADC_GAIN_1,
		.reference = ADC_REF_INTERNAL,
		.acquisition_time = ADC_ACQ_TIME_DEFAULT,
	};

	cfg.channel_id = channel;
	cfg.input_positive = input;
	adc_seq.channels = BIT(channel);
	adc_seq.buffer = &adc_sample;
	adc_seq.buffer_size = sizeof(adc_sample);
	adc_seq.resolution = 12;
	return adc_channel_setup(adc_dev, &cfg);
}


#define BUZZER_PIN 27

int main(void)
{
	int half_us = 1000;

	adc_setup(1, NRF_SAADC_AIN1);
	gpio_pin_configure(gpio0_dev, BUZZER_PIN, GPIO_OUTPUT_LOW);

	while (1) {
		if (adc_read(adc_dev, &adc_seq) == 0) {
			int freq = 100 + (int)adc_sample * 1900 / 4096;

			half_us = 500000 / freq;
		}
		/* ~20 carrier periods between ADC reads (<70 ms even at 290 Hz) */
		for (int i = 0; i < 20; ++i) {
			gpio_pin_set(gpio0_dev, BUZZER_PIN, 1);
			k_busy_wait(half_us);
			gpio_pin_set(gpio0_dev, BUZZER_PIN, 0);
			k_busy_wait(half_us);
		}
	}
	return 0;
}

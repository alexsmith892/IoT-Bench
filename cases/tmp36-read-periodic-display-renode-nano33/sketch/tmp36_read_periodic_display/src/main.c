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

#define RS_PORT gpio1_dev
#define RS_PIN 12
#define E_PORT gpio1_dev
#define E_PIN 14
#define D4_PORT gpio1_dev
#define D4_PIN 15
#define D5_PORT gpio1_dev
#define D5_PIN 13
#define D6_PORT gpio0_dev
#define D6_PIN 21
#define D7_PORT gpio0_dev
#define D7_PIN 27

static void lcd_write_nibble(int rs, int value)
{
	gpio_pin_set(RS_PORT, RS_PIN, rs);
	gpio_pin_set(D4_PORT, D4_PIN, (value >> 0) & 1);
	gpio_pin_set(D5_PORT, D5_PIN, (value >> 1) & 1);
	gpio_pin_set(D6_PORT, D6_PIN, (value >> 2) & 1);
	gpio_pin_set(D7_PORT, D7_PIN, (value >> 3) & 1);
	k_busy_wait(20);
	gpio_pin_set(E_PORT, E_PIN, 1);
	k_busy_wait(40);
	gpio_pin_set(E_PORT, E_PIN, 0);
	k_busy_wait(60);
}

static void lcd_write_byte(int rs, int value)
{
	lcd_write_nibble(rs, value >> 4);
	lcd_write_nibble(rs, value & 0x0F);
	k_msleep(1);
}

static void lcd_init(void)
{
	gpio_pin_configure(RS_PORT, RS_PIN, GPIO_OUTPUT_LOW);
	gpio_pin_configure(E_PORT, E_PIN, GPIO_OUTPUT_LOW);
	gpio_pin_configure(D4_PORT, D4_PIN, GPIO_OUTPUT_LOW);
	gpio_pin_configure(D5_PORT, D5_PIN, GPIO_OUTPUT_LOW);
	gpio_pin_configure(D6_PORT, D6_PIN, GPIO_OUTPUT_LOW);
	gpio_pin_configure(D7_PORT, D7_PIN, GPIO_OUTPUT_LOW);
	k_msleep(50);
	lcd_write_nibble(0, 0x3);
	k_msleep(5);
	lcd_write_nibble(0, 0x3);
	k_msleep(1);
	lcd_write_nibble(0, 0x3);
	k_msleep(1);
	lcd_write_nibble(0, 0x2);
	k_msleep(1);
	lcd_write_byte(0, 0x28); /* 4-bit, 2 lines */
	lcd_write_byte(0, 0x0C); /* display on */
	lcd_write_byte(0, 0x01); /* clear */
	k_msleep(2);
	lcd_write_byte(0, 0x06); /* entry mode */
}

static void lcd_clear(void)
{
	lcd_write_byte(0, 0x01);
	k_msleep(2);
}

static void lcd_goto(int row, int col)
{
	lcd_write_byte(0, 0x80 | (row ? 0x40 : 0x00) | col);
}

static void lcd_print(const char *text)
{
	while (*text) {
		lcd_write_byte(1, (unsigned char)*text++);
	}
}

#define BTN_PIN 11

static struct gpio_callback btn_cb;
static volatile bool reset_requested;

static void on_press(const struct device *port, struct gpio_callback *cb, uint32_t pins)
{
	reset_requested = true;
}

int main(void)
{
	char prev[17] = "";
	char line[17];
	int counter = 0;

	adc_setup(0, NRF_SAADC_AIN0);
	gpio_pin_configure(gpio1_dev, BTN_PIN, GPIO_INPUT);
	gpio_init_callback(&btn_cb, on_press, BIT(BTN_PIN));
	gpio_add_callback(gpio1_dev, &btn_cb);
	gpio_pin_interrupt_configure(gpio1_dev, BTN_PIN, GPIO_INT_EDGE_RISING);
	lcd_init();

	while (1) {
		k_msleep(1000);
		if (reset_requested) {
			reset_requested = false;
			counter = 0;
			prev[0] = '\0';
			lcd_clear();
		}
		if (adc_read(adc_dev, &adc_seq) == 0) {
			counter++;
			snprintf(line, sizeof(line), "Temp #%d: %d F", counter, (int)adc_sample);
			lcd_clear();
			if (prev[0] != '\0') {
				lcd_goto(0, 0);
				lcd_print(prev);
				lcd_goto(1, 0);
			} else {
				lcd_goto(1, 0);
			}
			lcd_print(line);
			snprintf(prev, sizeof(prev), "%s", line);
		}
	}
	return 0;
}

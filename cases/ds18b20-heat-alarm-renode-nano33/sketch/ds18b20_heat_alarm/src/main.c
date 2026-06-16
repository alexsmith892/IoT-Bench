#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(my_led), gpios);
static const struct gpio_dt_spec buzzer = GPIO_DT_SPEC_GET(DT_ALIAS(my_buzzer), gpios);

static const struct gpio_dt_spec ds = GPIO_DT_SPEC_GET(DT_ALIAS(data_ds18b20), gpios);

/* Renode's GPIO connections are unidirectional, so the open-drain bus release
 * is invisible to the slave model. Drive the line push-pull during the reset
 * and write phases (so the model observes the master's edges and low-pulse
 * widths) and only release it during a read slot so the model can answer. The
 * bit windows are a deliberate ~10x stretch of the real DS18B20 timing so the
 * simulator's ~30 us RTC resolution can resolve them; the task prompt
 * documents the scale a submission must target. */
static void ow_low(void)
{
	gpio_pin_configure_dt(&ds, GPIO_OUTPUT_LOW);
}

static void ow_high(void)
{
	gpio_pin_configure_dt(&ds, GPIO_OUTPUT_HIGH);
}

static void ow_release(void)
{
	gpio_pin_configure_dt(&ds, GPIO_INPUT | GPIO_PULL_UP);
}

static int ow_reset(void)
{
	int presence;

	ow_low();
	k_busy_wait(2000);
	ow_high();
	ow_release();
	k_busy_wait(90);
	presence = gpio_pin_get_dt(&ds) == 0;
	k_busy_wait(600);
	ow_high();
	return presence ? 0 : -1;
}

static void ow_write_bit(int bit)
{
	ow_low();
	if (bit) {
		k_busy_wait(30);
		ow_high();
		k_busy_wait(400);
	} else {
		k_busy_wait(400);
		ow_high();
		k_busy_wait(30);
	}
}

static int ow_read_bit(void)
{
	int bit;

	ow_low();
	k_busy_wait(60);
	ow_release();
	k_busy_wait(120);
	bit = gpio_pin_get_dt(&ds);
	k_busy_wait(300);
	ow_high();
	return bit;
}

static void ow_write_byte(uint8_t value)
{
	for (int i = 0; i < 8; ++i) {
		ow_write_bit((value >> i) & 1);
	}
}

static uint8_t ow_read_byte(void)
{
	uint8_t value = 0;

	for (int i = 0; i < 8; ++i) {
		value |= ow_read_bit() << i;
	}
	return value;
}

static uint8_t ow_crc8(const uint8_t *data, int count)
{
	uint8_t crc = 0;

	for (int i = 0; i < count; ++i) {
		uint8_t in = data[i];
		for (int bit = 0; bit < 8; ++bit) {
			uint8_t mix = (crc ^ in) & 1;
			crc >>= 1;
			if (mix) {
				crc ^= 0x8C;
			}
			in >>= 1;
		}
	}
	return crc;
}

static int ds18b20_read_c_x16(int *temp_x16)
{
	uint8_t scratch[9];

	if (ow_reset() != 0) {
		return -1;
	}
	ow_write_byte(0xCC);
	ow_write_byte(0x44);
	k_msleep(100);
	if (ow_reset() != 0) {
		return -1;
	}
	ow_write_byte(0xCC);
	ow_write_byte(0xBE);
	for (int i = 0; i < 9; ++i) {
		scratch[i] = ow_read_byte();
	}
	if (ow_crc8(scratch, 8) != scratch[8]) {
		return -2;
	}
	*temp_x16 = (int16_t)((scratch[1] << 8) | scratch[0]);
	return 0;
}

int main(void)
{
	gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
	gpio_pin_configure_dt(&buzzer, GPIO_OUTPUT_INACTIVE);
	while (1) {
		int temp_x16 = 0;
		if (ds18b20_read_c_x16(&temp_x16) == 0 && temp_x16 > 30 * 16) {
			gpio_pin_set_dt(&buzzer, 1);
			gpio_pin_toggle_dt(&led);
			k_msleep(80);
		} else {
			gpio_pin_set_dt(&buzzer, 0);
			gpio_pin_set_dt(&led, 0);
			k_msleep(80);
		}
	}
	return 0;
}

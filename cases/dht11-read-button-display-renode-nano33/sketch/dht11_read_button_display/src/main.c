#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <stdio.h>

static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(DT_ALIAS(my_button), gpios);
static struct gpio_callback button_cb;
static volatile bool requested;
static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

static const struct gpio_dt_spec dht = GPIO_DT_SPEC_GET(DT_ALIAS(data_dht11), gpios);

static int wait_level(int level, uint32_t timeout_us)
{
	uint32_t start = k_cycle_get_32();
	uint32_t timeout = k_us_to_cyc_ceil32(timeout_us);

	while (gpio_pin_get_dt(&dht) != level) {
		if ((uint32_t)(k_cycle_get_32() - start) > timeout) {
			return -1;
		}
	}
	return 0;
}

static int dht11_read(int *temperature, int *humidity)
{
	uint8_t data[5] = {0};

	gpio_pin_configure_dt(&dht, GPIO_OUTPUT_HIGH);
	k_busy_wait(50);
	gpio_pin_set_dt(&dht, 0);
	k_msleep(20);
	gpio_pin_configure_dt(&dht, GPIO_INPUT | GPIO_PULL_UP);

	if (wait_level(0, 3000) != 0 || wait_level(1, 3000) != 0 || wait_level(0, 3000) != 0) {
		return -1;
	}
	for (int bit = 0; bit < 40; ++bit) {
		uint32_t high_start, high_us;

		if (wait_level(1, 3000) != 0) {
			return -1;
		}
		high_start = k_cycle_get_32();
		if (wait_level(0, 3000) != 0) {
			return -1;
		}
		high_us = k_cyc_to_us_floor32(k_cycle_get_32() - high_start);
		data[bit / 8] <<= 1;
		if (high_us > 1000) {
			data[bit / 8] |= 1;
		}
	}
	if (((data[0] + data[1] + data[2] + data[3]) & 0xFF) != data[4]) {
		return -2;
	}
	*humidity = data[0];
	*temperature = data[2];
	return 0;
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

static void on_button(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(cb);
	ARG_UNUSED(pins);
	requested = true;
}

static void show_reading(void)
{
	int temperature = 0;
	int humidity = 0;
	char line[17];

	if (dht11_read(&temperature, &humidity) != 0) {
		lcd_clear();
		lcd_print("DHT11 error");
		return;
	}
	lcd_clear();
	lcd_goto(0, 0);
	snprintf(line, sizeof(line), "Temp: %d.0 C", temperature);
	lcd_print(line);
	lcd_goto(1, 0);
	snprintf(line, sizeof(line), "RH: %d.0 %%", humidity);
	lcd_print(line);
}

int main(void)
{
	gpio_pin_configure_dt(&button, GPIO_INPUT | GPIO_PULL_UP);
	gpio_pin_interrupt_configure_dt(&button, GPIO_INT_EDGE_TO_ACTIVE);
	gpio_init_callback(&button_cb, on_button, BIT(button.pin));
	gpio_add_callback(button.port, &button_cb);
	lcd_init();
	requested = true;
	while (1) {
		if (requested) {
			requested = false;
			show_reading();
		}
		k_msleep(20);
	}
	return 0;
}

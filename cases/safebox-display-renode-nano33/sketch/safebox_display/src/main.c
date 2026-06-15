#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <stdio.h>

static const struct device *const gpio0_dev = DEVICE_DT_GET(DT_NODELABEL(gpio0));
static const struct device *const gpio1_dev = DEVICE_DT_GET(DT_NODELABEL(gpio1));

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

#define RELAY_PIN 13

static const int row_pins[2] = {11, 2};
static const char legend[2][3] = {{'1', '2', '3'}, {'4', '5', '6'}};

int main(void)
{
	const struct device *col_ports[3] = {gpio1_dev, gpio1_dev, gpio0_dev};
	const int col_pins[3] = {1, 8, 23};
	bool held[2][3] = {0};
	char entered[5] = {0};
	int count = 0;
	bool unlocked = false;
	char line[17];

	gpio_pin_configure(gpio0_dev, RELAY_PIN, GPIO_OUTPUT_LOW);
	for (int r = 0; r < 2; ++r) {
		gpio_pin_configure(gpio1_dev, row_pins[r], GPIO_OUTPUT_HIGH);
	}
	for (int c = 0; c < 3; ++c) {
		gpio_pin_configure(col_ports[c], col_pins[c], GPIO_INPUT);
	}
	lcd_init();

	while (1) {
		for (int r = 0; r < 2; ++r) {
			gpio_pin_set_raw(gpio1_dev, row_pins[r], 0);
			k_msleep(1);
			for (int c = 0; c < 3; ++c) {
				bool pressed = gpio_pin_get_raw(col_ports[c], col_pins[c]) == 0;

				if (pressed && !held[r][c] && !unlocked && count < 4) {
					entered[count++] = legend[r][c];
				}
				held[r][c] = pressed;
			}
			gpio_pin_set_raw(gpio1_dev, row_pins[r], 1);
		}
		if (count == 4) {
			bool match = entered[0] == '1' && entered[1] == '2' &&
				     entered[2] == '3' && entered[3] == '4';

			lcd_clear();
			lcd_goto(0, 0);
			snprintf(line, sizeof(line), "Input: %s", entered);
			lcd_print(line);
			lcd_goto(1, 0);
			lcd_print(match ? "Status: Success" : "Status: Fail");
			if (match) {
				unlocked = true;
				gpio_pin_set(gpio0_dev, RELAY_PIN, 1);
			}
			count = 0;
		}
		k_msleep(5);
	}
	return 0;
}

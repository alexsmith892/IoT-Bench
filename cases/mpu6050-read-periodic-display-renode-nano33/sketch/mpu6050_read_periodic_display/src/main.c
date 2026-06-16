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
#include <zephyr/drivers/i2c.h>

#define MPU6050_ADDR 0x68

static const struct device *const i2c_dev = DEVICE_DT_GET(DT_NODELABEL(i2c0));

static int mpu_read(int16_t accel[3], int16_t gyro[3])
{
	uint8_t raw[14];

	if (i2c_burst_read(i2c_dev, MPU6050_ADDR, 0x3B, raw, sizeof(raw)) != 0) {
		return -1;
	}
	for (int i = 0; i < 3; ++i) {
		accel[i] = (int16_t)((raw[2 * i] << 8) | raw[2 * i + 1]);
		gyro[i] = (int16_t)((raw[8 + 2 * i] << 8) | raw[9 + 2 * i]);
	}
	return 0;
}

static void lcd_show_imu(int ax, int ay, int az, int gx, int gy, int gz)
{
	char line[17];

	lcd_clear();
	lcd_goto(0, 0);
	snprintf(line, sizeof(line), "Accel: %d %d %d", ax, ay, az);
	lcd_print(line);
	lcd_goto(1, 0);
	snprintf(line, sizeof(line), "Gyro: %d %d %d", gx, gy, gz);
	lcd_print(line);
}


#define SAMPLES 10

int main(void)
{
	int16_t accel[3], gyro[3];
	int32_t acc_sum[3] = {0};
	int32_t gyr_sum[3] = {0};
	int count = 0;

	(void)i2c_reg_write_byte(i2c_dev, MPU6050_ADDR, 0x6B, 0x00);
	lcd_init();

	while (1) {
		if (mpu_read(accel, gyro) == 0) {
			for (int i = 0; i < 3; ++i) {
				acc_sum[i] += accel[i];
				gyr_sum[i] += gyro[i];
			}
			count++;
			if (count >= SAMPLES) {
				lcd_show_imu(acc_sum[0] / SAMPLES, acc_sum[1] / SAMPLES,
					     acc_sum[2] / SAMPLES, gyr_sum[0] / SAMPLES,
					     gyr_sum[1] / SAMPLES, gyr_sum[2] / SAMPLES);
				for (int i = 0; i < 3; ++i) {
					acc_sum[i] = 0;
					gyr_sum[i] = 0;
				}
				count = 0;
			}
		}
		k_msleep(100);
	}
	return 0;
}

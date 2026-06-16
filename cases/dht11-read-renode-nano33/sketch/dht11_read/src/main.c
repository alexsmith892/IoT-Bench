#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

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

int main(void)
{
	while (1) {
		int temperature = 0;
		int humidity = 0;
		int rc = dht11_read(&temperature, &humidity);

		if (rc == 0) {
			printk("Temperature: %d C Humidity: %d %%\n", temperature, humidity);
		} else {
			printk("DHT11 checksum/read error\n");
		}
		k_msleep(800);
	}
	return 0;
}

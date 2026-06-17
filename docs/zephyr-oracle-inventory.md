# Zephyr Nano 33 BLE Oracle Inventory

This inventory records the anti-gaming mechanism for the Zephyr/Renode
catalog. The canonical table has exactly one row for each upstream canonical
task. The local `lsm9ds1_read_i2c` addition is listed separately and is not part
of the canonical count.

## Canonical Tasks

| Task | Level | Oracle defense |
|---|---|---|
| `blink_led_1hz` | level1 | fixed-by-spec `waveform_frequency` checks the LED is 1 Hz rather than accepting a compile-only or serial-only stub. |
| `blink_led_morse_code` | level1 | fixed-by-spec `morse_sos` checks SOS high and gap units on the LED waveform. |
| `blink_led_no_delay` | level1 | fixed-by-spec `no_delay_static_plus_waveform` rejects delay loops and validates the LED waveform. |
| `blink_two_leds` | level1 | fixed-by-spec `no_delay_static_plus_waveform` validates both LED channels and rejects blocking delay loops. |
| `breathing_led` | level1 | fixed-by-spec `pwm_breathing` checks 50 duty levels and ramp timing on the LED waveform. |
| `button_press_debounce` | level1 | Behavior-distinct variants `two_presses` and `three_presses` plus `debounce_serial` tied to the bounced button sequence. |
| `button_status_count` | level1 | Behavior-distinct variants `three_presses` and `four_presses` plus `serial_count_sequence` tied to button presses. |
| `button_status_display` | level1 | `serial_contains_on_stimulus` requires the displayed text to appear for the button press scenario. |
| `buzzer_button` | level1 | `stimulus_to_output` correlates buzzer waveform activity to the button press sequence. |
| `buzzer_doorbell` | level1 | `stimulus_to_output` correlates buzzer waveform activity to the button press scenario. |
| `sensor_pir_human_motion` | level1 | Behavior-distinct variants `single_motion` and `double_motion` plus serial output tied to PIR state changes. |
| `tmp36_read` | level1 | Behavior-distinct variants `rising` and `falling` plus analog-temperature serial ranges tied to ADC stimulus. |
| `16key_keypad` | level2 | Behavior-distinct variants `one_two_three_four` and `seven_five_nine_zero` plus `serial_observation_sequence` tied to key controls. |
| `bme280_read_i2c` | level2 | Behavior-distinct variants `warm_humid` and `hot_dry` plus I2C static checks and `bme280_environment` output ranges. |
| `bme280_read_spi` | level2 | Behavior-distinct variants `warm_humid` and `hot_dry` plus SPI static checks and `bme280_environment` output ranges. |
| `clap_switch` | level2 | `stimulus_to_output` ties LED waveform state changes to the clap control sequence. |
| `dht11_read` | level2 | Behavior-distinct variants `cool_dry` and `warm_humid` plus `serial_observation_sequence` tied to sensor data. |
| `ds1307_rtc` | level2 | Behavior-distinct variants `feb_afternoon` and `jul_morning` plus RTC serial regex sequence. |
| `ds18b20_heat_alarm` | level2 | Behavior-distinct variants `cold_then_hot` and `stays_cold` plus `window_ratios` tied to temperature controls. |
| `hcsr04_find_distance` | level2 | Behavior-distinct variants `far` and `near` plus pulse static checks and distance serial observations. |
| `hcsr501_motion_alarm` | level2 | `stimulus_to_output` correlates alarm waveform activity to PIR state changes. |
| `lcd1602_display_hello_world` | level2 | fixed-by-spec `lcd_text` decodes the LCD bus and requires the literal Hello World display. |
| `mpu6050_read_i2c` | level2 | Behavior-distinct variants `half_g` and `one_and_half_g` plus I2C static checks and serial observation ranges. |
| `parking_sensor` | level2 | `window_ratios` and `frequency_windows` check buzzer timing windows for the fixed parking-distance model. |
| `photoresistor_nightlight` | level2 | Behavior-distinct variants `bright_then_dark` and `dark_then_bright` plus `stimulus_to_output` tied to analog controls. |
| `reverse_parking_sensor` | level2 | `frequency_windows` checks the buzzer cadence for the fixed reverse-parking-distance model. |
| `rotary_encoder` | level2 | Behavior-distinct variants `three_cw_two_ccw` and `one_cw_four_ccw` plus serial sequence tied to encoder controls. |
| `tilt_detection_alarm` | level2 | `stimulus_to_output` correlates alarm waveform activity to the tilt control sequence. |
| `buzzer_laser_tripwire` | level3 | Behavior-distinct variants `clear_then_blocked` and `blocked_then_clear` plus `window_ratios` and stimulus correlation. |
| `buzzer_toggle_led_freq` | level3 | `bus_activity` and `frequency_windows` require buzzer activity and LED frequency changes after button presses. |
| `dht11_read_button_display` | level3 | Behavior-distinct variants `cool_dry_then_warm_humid` and `cool_dry_then_hot_sticky` plus `lcd_text_sequence`. |
| `joystick_buzzer_pitch` | level3 | Behavior-distinct variants `low_then_high` and `high_then_low` plus `frequency_windows` tied to joystick ADC controls. |
| `lcd1602_auto_brightness_control` | level3 | Behavior-distinct variants `bright_then_dark` and `dark_then_bright` plus `window_ratios` tied to brightness controls. |
| `mpu6050_read_button_display` | level3 | Behavior-distinct variants `half_g` and `one_and_half_g` plus button-triggered `lcd_text_sequence`. |
| `mpu6050_read_periodic_display` | level3 | Behavior-distinct variants `half_g` and `one_and_half_g` plus periodic `lcd_text_sequence`. |
| `reaction_timer_display` | level3 | Behavior-distinct variants `quick_reaction` and `slow_reaction` with LCD regex windows for different reaction times. |
| `safebox` | level3 | Behavior-distinct variants `unlocks_second` and `never_correct` plus keypad `window_ratios`. |
| `safebox_display` | level3 | Behavior-distinct variants `wrong_1235` and `wrong_1325` plus `lcd_text_sequence` and lock LED `window_ratios`. |
| `sensor_water_level_display` | level3 | Behavior-distinct variants `rising` and `falling` plus `lcd_text_sequence` tied to analog water-level controls. |
| `step_counter_print` | level3 | Behavior-distinct variants `three_steps` and `four_steps` plus `serial_count_sequence` tied to step controls. |
| `tmp36_read_button_display` | level3 | Behavior-distinct variants `warm` and `hot` plus button-triggered LCD regex ranges for Fahrenheit output. |
| `tmp36_read_periodic_display` | level3 | Behavior-distinct variants `low_to_mid` and `high_to_low` plus periodic `lcd_text_sequence` tied to ADC controls. |

## Non-Canonical Addition

| Task | Level | Oracle defense |
|---|---|---|
| `lsm9ds1_read_i2c` | level2 | Behavior-distinct variants `half_g` and `one_and_half_g` plus I2C static checks and serial observation ranges. |

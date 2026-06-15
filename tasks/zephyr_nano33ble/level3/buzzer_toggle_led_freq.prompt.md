# Button-Controlled LED Frequency And Buzzer

Use a button to cycle through LED blink modes. Each button press should advance
the mode and briefly beep the buzzer. The LED modes are 1 Hz, 2 Hz, 4 Hz, and
off, repeating in that order.

For this Zephyr/Renode case the button is on GPIO port 1, pin 11 and is
active-high. The LED output is on GPIO port 0, pin 16. The active buzzer is on
GPIO port 1, pin 12. Implement the timing without blocking long enough to miss
button edges.

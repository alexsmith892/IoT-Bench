# HC-SR501 Motion Alarm

Read a digital HC-SR501-style PIR motion signal and drive an active buzzer
while motion is detected. Turn the buzzer off when the motion signal returns
low.

For this Zephyr/Renode case the PIR signal is a digital surrogate on GPIO port
1, pin 15. The active buzzer is on GPIO port 1, pin 12. The input is
active-high.

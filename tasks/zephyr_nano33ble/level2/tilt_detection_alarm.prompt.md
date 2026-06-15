# Tilt Detection Alarm

Read a digital tilt-switch signal and turn on an active buzzer while the tilt
switch is active. Turn the buzzer off when the tilt signal is inactive.

For this Zephyr/Renode case the tilt switch is represented by an active-high
digital input on GPIO port 1, pin 15. The active buzzer is on GPIO port 1,
pin 12.

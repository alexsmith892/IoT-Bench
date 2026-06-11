Build the circuit that integrates the button press with both the buzzer and the timer-based LED control. After the system reset, when you press the button:
For the 1st time, a timer is triggered that toggles the external LED at 1 Hz;
For the 2nd time, a timer is triggered that toggles the external LED at 2 Hz;
For the 3rd time, a timer is triggered that toggles the external LED at 4 Hz;
For the 4th time, the timer is stopped and the external LED will not blink;
The process repeats and the toggling frequency of the LED will undergo the sequence of 1 Hz, 2 Hz, 4 Hz, N/A, 1 Hz, 2 Hz, 4 Hz, N/A, … as you press the button. In addition, every time the button is pressed, the buzzer will go off, indicating that the button has been pressed. The timing diagram is given below. The button and buzzer must be connected to separate GPIO pins, and the buzzer operation will be triggered by its own connected GPIO pin.
LED: GPIO 4, Buzzer: GPIO 3, Button: GPIO 2.

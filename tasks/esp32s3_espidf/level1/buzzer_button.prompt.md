Read the state of an active-low pull-up button, and turn on the buzzer when the button is pressed. Implement software debouncing to avoid multiple triggers.
Use GPIO 12 for the button and GPIO 13 for the buzzer; the pressed state reads LOW.
Use ESP-IDF APIs, not Arduino APIs. Implement the app in `main/main.c` with `app_main`.

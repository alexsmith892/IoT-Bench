Read the state of an active-low pull-up button and implement software debouncing to avoid multiple triggers. Print "Button Pressed!" to the serial console when the button is pressed.
Use GPIO 12 for the button; the pressed state reads LOW.
Use ESP-IDF APIs, not Arduino APIs. Implement the app in `main/main.c` with `app_main`.

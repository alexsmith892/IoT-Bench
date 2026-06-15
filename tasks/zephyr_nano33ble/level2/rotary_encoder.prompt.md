Target: Arduino Nano 33 BLE (nRF52840) running Zephyr RTOS.

Track the position and rotation direction of a quadrature rotary encoder
(KY-040 style) and print one line to the serial console for each detent, in
this shape:

Position: <n> Direction: <CW|CCW>

The encoder's CLK signal is on GPIO port 1, pin 11 and DT is on GPIO port
1, pin 12. Both lines idle HIGH and pulse LOW as the shaft turns. One
detent is one full quadrature cycle: for clockwise rotation CLK falls
first (CLK,DT goes 11 -> 01 -> 00 -> 10 -> 11), for counter-clockwise DT
falls first. The position starts at 0, increments by 1 per clockwise
detent, and decrements by 1 per counter-clockwise detent (it may go
negative). Print exactly one line per detent, after the cycle completes.

Implement the application in `src/main.c` with a `main` function. Use only
the Zephyr core APIs and in-tree drivers (e.g. `zephyr/drivers/gpio.h`,
`zephyr/kernel.h`, `printk`); do not use external modules or third-party
libraries.

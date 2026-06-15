# Clap Switch

Read a digital sound-sensor signal and toggle a relay output once for each
clap event. A rising edge on the sound-sensor signal should change the relay
state; holding the input high must not repeatedly toggle the relay.

For this Zephyr/Renode case the sound sensor is represented by an active-high
digital input on GPIO port 1, pin 15. The relay output is represented by a
GPIO output on port 0, pin 16.

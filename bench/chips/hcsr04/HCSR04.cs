//
// IoT-Bench deterministic HC-SR04 ultrasonic sensor model for Renode.
//
// Loaded at runtime via `include @.../HCSR04.cs` before the platform
// description. The firmware drives the TRIG pin (wired into GPIO input 0 of
// this model); on the falling edge of a trigger pulse the model raises the
// ECHO output after a fixed 200 us sonic-burst delay and holds it high for
// 58 us per centimeter of the configured distance (the standard HC-SR04
// scale), all in exact virtual time via 1 MHz one-shot timers.
//
// DistanceCm is settable from the generated .repl/.resc (fixture attrs and
// per-variant overrides), mirroring the Wokwi HC-SR04 `distance` attr.
//
// Like the other IoT-Bench GPIO-only models it is registered on the system
// bus at an unused address purely to have a monitor name; the register
// window is inert.
//
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class IoTBench_HCSR04 : IDoubleWordPeripheral, IKnownSize, IGPIOReceiver
    {
        public IoTBench_HCSR04(IMachine machine)
        {
            Echo = new GPIO();
            DistanceCm = 100m;
            riseTimer = new LimitTimer(machine.ClockSource, TimerFrequency, this, "echoRise",
                limit: 1, direction: Direction.Ascending, enabled: false,
                workMode: WorkMode.OneShot, eventEnabled: true);
            fallTimer = new LimitTimer(machine.ClockSource, TimerFrequency, this, "echoFall",
                limit: 1, direction: Direction.Ascending, enabled: false,
                workMode: WorkMode.OneShot, eventEnabled: true);
            riseTimer.LimitReached += OnEchoRise;
            fallTimer.LimitReached += OnEchoFall;
            Reset();
        }

        // Simulated obstacle distance in centimeters (echo width 58 us/cm).
        public decimal DistanceCm { get; set; }

        public void Reset()
        {
            triggerLevel = false;
            Echo.Set(false);
            riseTimer.Enabled = false;
            fallTimer.Enabled = false;
        }

        public long Size => 0x1000;

        public GPIO Echo { get; }

        public void OnGPIO(int number, bool value)
        {
            if(number != 0)
            {
                this.Log(LogLevel.Warning, "HC-SR04 has only the TRIG input (0), got {0}", number);
                return;
            }
            // Measurement starts when the trigger pulse ends.
            var fallingEdge = triggerLevel && !value;
            triggerLevel = value;
            if(!fallingEdge)
            {
                return;
            }
            var widthUs = (ulong)Math.Max(1, Math.Round(DistanceCm * 58m));
            ScheduleOneShot(riseTimer, BurstDelayUs);
            ScheduleOneShot(fallTimer, BurstDelayUs + widthUs);
        }

        public uint ReadDoubleWord(long offset)
        {
            return 0;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            // Inert register window; sysbus mapping exists for the monitor name.
        }

        private void OnEchoRise()
        {
            Echo.Set(true);
        }

        private void OnEchoFall()
        {
            Echo.Set(false);
        }

        private static void ScheduleOneShot(LimitTimer timer, ulong microseconds)
        {
            timer.Enabled = false;
            timer.Limit = microseconds;
            timer.ResetValue();
            timer.Enabled = true;
        }

        private const long TimerFrequency = 1000000; // 1 MHz -> 1 us resolution
        private const ulong BurstDelayUs = 200;

        private readonly LimitTimer riseTimer;
        private readonly LimitTimer fallTimer;
        private bool triggerLevel;
    }
}

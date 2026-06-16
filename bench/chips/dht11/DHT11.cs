//
// IoT-Bench deterministic DHT11 model for Renode.
//
// The model implements the DHT11 single-wire transaction used by the benchmark:
// firmware pulls DATA low for a start condition, releases it, then samples the
// sensor's 80 us response and 40 humidity/temperature bits. Temperature and
// humidity are settable from the generated .resc via decimal properties.
//
using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class IoTBench_DHT11 : IDoubleWordPeripheral, IKnownSize, IGPIOReceiver
    {
        public IoTBench_DHT11(IMachine machine)
        {
            this.machine = machine;
            Data = new GPIO();
            responseTimer = new LimitTimer(machine.ClockSource, TimerFrequency, this, "dht11Response",
                limit: 1, direction: Direction.Ascending, enabled: false,
                workMode: WorkMode.OneShot, eventEnabled: true);
            responseTimer.LimitReached += OnTimer;
            Temperature = 24m;
            Humidity = 40m;
            Reset();
        }

        public decimal Temperature { get; set; }
        public decimal Humidity { get; set; }
        public GPIO Data { get; }
        public long Size => 0x1000;

        public void Reset()
        {
            lastLevel = true;
            armed = false;
            responseActive = false;
            events.Clear();
            responseTimer.Enabled = false;
            Data.Set(true);
        }

        public void OnGPIO(int number, bool value)
        {
            if(number != 0)
            {
                this.Log(LogLevel.Warning, "DHT11 has only DATA input 0, got {0}", number);
                return;
            }
            // The bus idles high (pull-up). The nRF GPIO OUT register powers up
            // low, so the line is low at boot before the firmware drives it;
            // arm only once a genuine high has been seen so that boot-time low
            // is ignored and the response triggers on the real high->low start.
            if(value)
            {
                armed = true;
            }
            if(armed && lastLevel && !value && !responseActive)
            {
                QueueResponse();
            }
            lastLevel = value;
        }

        public uint ReadDoubleWord(long offset) => 0;
        public void WriteDoubleWord(long offset, uint value) {}

        private void QueueResponse()
        {
            events.Clear();
            responseActive = true;
            Enqueue(20500, false); // start low plus response-low delay
            Enqueue(500, true);    // response high
            Enqueue(500, false);   // first bit preamble low

            // Enqueue(delay, level) holds the *previous* level for `delay` us
            // and then drives `level`, so the HIGH pulse width is the delay of
            // the following low transition. The benchmark firmware times each
            // high pulse and treats >1000 us as a 1. These 500/1500 us widths
            // are a deliberate ~10x-stretched surrogate of the real DHT11
            // 26/70 us timing so Renode's virtual-time / RTC resolution
            // (~30 us) can discriminate them; the task prompt documents the
            // scale a submission must target.
            foreach(var bit in FrameBits())
            {
                Enqueue(500, true);                   // 500 us inter-bit low, then high
                Enqueue(bit ? 1500UL : 500UL, false); // hold high for the bit width
            }
            Enqueue(500, true);
            ScheduleNext();
        }

        private IEnumerable<bool> FrameBits()
        {
            var rh = ClampByte(Humidity);
            var temp = ClampByte(Temperature);
            var frame = new byte[] { rh, 0, temp, 0, (byte)((rh + temp) & 0xFF) };
            foreach(var b in frame)
            {
                for(var bit = 7; bit >= 0; bit--)
                {
                    yield return ((b >> bit) & 1) != 0;
                }
            }
        }

        private static byte ClampByte(decimal value)
        {
            if(value < 0m) return 0;
            if(value > 255m) return 255;
            return (byte)Math.Round(value);
        }

        private void Enqueue(ulong delayUs, bool level)
        {
            events.Enqueue(new ScheduledLevel(delayUs, level));
        }

        private void ScheduleNext()
        {
            if(events.Count == 0)
            {
                responseActive = false;
                return;
            }
            var next = events.Dequeue();
            nextLevel = next.Level;
            responseTimer.Enabled = false;
            responseTimer.Limit = Math.Max(1UL, next.DelayUs);
            responseTimer.ResetValue();
            responseTimer.Enabled = true;
        }

        private void OnTimer()
        {
            Data.Set(nextLevel);
            ScheduleNext();
        }

        private const long TimerFrequency = 1000000;

        private readonly IMachine machine;
        private readonly LimitTimer responseTimer;
        private readonly Queue<ScheduledLevel> events = new Queue<ScheduledLevel>();
        private bool lastLevel;
        private bool armed;
        private bool nextLevel;
        private bool responseActive;

        private struct ScheduledLevel
        {
            public ScheduledLevel(ulong delayUs, bool level)
            {
                DelayUs = delayUs;
                Level = level;
            }

            public ulong DelayUs;
            public bool Level;
        }
    }
}

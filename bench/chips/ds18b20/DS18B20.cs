//
// IoT-Bench deterministic DS18B20 model for Renode.
//
// Implements the subset of the 1-Wire protocol needed by the benchmark:
// reset/presence, SKIP_ROM, CONVERT_T, and READ_SCRATCHPAD. Command bytes are
// received LSB-first from master write slots; scratchpad bytes are returned
// LSB-first in master read slots. Temperature is settable from .resc.
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
    public class IoTBench_DS18B20 : IDoubleWordPeripheral, IKnownSize, IGPIOReceiver
    {
        public IoTBench_DS18B20(IMachine machine)
        {
            this.machine = machine;
            Data = new GPIO();
            timer = new LimitTimer(machine.ClockSource, TimerFrequency, this, "ds18b20",
                limit: 1, direction: Direction.Ascending, enabled: false,
                workMode: WorkMode.OneShot, eventEnabled: true);
            timer.LimitReached += OnTimer;
            Temperature = 22m;
            Reset();
        }

        public decimal Temperature { get; set; }
        public GPIO Data { get; }
        public long Size => 0x1000;

        public void Reset()
        {
            lastLevel = true;
            lowStartedAt = NowUs();
            command = 0;
            commandBits = 0;
            sendingScratchpad = false;
            sendBitIndex = 0;
            events.Clear();
            timer.Enabled = false;
            Data.Set(true);
        }

        public void OnGPIO(int number, bool value)
        {
            if(number != 0)
            {
                this.Log(LogLevel.Warning, "DS18B20 has only DATA input 0, got {0}", number);
                return;
            }
            var now = NowUs();
            if(lastLevel && !value)
            {
                lowStartedAt = now;
            }
            else if(!lastLevel && value)
            {
                var lowDuration = now - lowStartedAt;
                if(lowDuration >= ResetLowThresholdUs)
                {
                    OnResetPulse();
                }
                else if(sendingScratchpad)
                {
                    OnReadSlot();
                }
                else
                {
                    OnWriteSlot(lowDuration >= WriteZeroThresholdUs ? 0 : 1);
                }
            }
            lastLevel = value;
        }

        public uint ReadDoubleWord(long offset) => 0;
        public void WriteDoubleWord(long offset, uint value) {}

        private void OnResetPulse()
        {
            command = 0;
            commandBits = 0;
            sendingScratchpad = false;
            sendBitIndex = 0;
            events.Clear();
            Enqueue(30, false);
            Enqueue(180, true);
            ScheduleNext();
        }

        private void OnWriteSlot(int bit)
        {
            command |= (byte)(bit << commandBits);
            commandBits++;
            if(commandBits < 8)
            {
                return;
            }
            switch(command)
            {
                case 0xCC: // SKIP_ROM
                case 0x44: // CONVERT_T
                    break;
                case 0xBE: // READ_SCRATCHPAD
                    scratchpad = BuildScratchpad();
                    sendingScratchpad = true;
                    sendBitIndex = 0;
                    break;
                default:
                    this.Log(LogLevel.Warning, "Unsupported DS18B20 command 0x{0:X2}", command);
                    break;
            }
            command = 0;
            commandBits = 0;
        }

        private void OnReadSlot()
        {
            var byteIndex = sendBitIndex / 8;
            var bitIndex = sendBitIndex % 8;
            var bit = byteIndex < scratchpad.Length ? ((scratchpad[byteIndex] >> bitIndex) & 1) : 1;
            sendBitIndex++;
            if(sendBitIndex >= scratchpad.Length * 8)
            {
                sendingScratchpad = false;
            }
            events.Clear();
            if(bit == 0)
            {
                Enqueue(4, false);
                Enqueue(52, true);
                ScheduleNext();
            }
            else
            {
                Data.Set(true);
            }
        }

        private byte[] BuildScratchpad()
        {
            var raw = (short)Math.Round(Temperature * 16m);
            var result = new byte[9];
            result[0] = (byte)(raw & 0xFF);
            result[1] = (byte)((raw >> 8) & 0xFF);
            result[2] = 75;      // TH
            result[3] = 70;      // TL
            result[4] = 0x7F;    // 12-bit resolution
            result[5] = 0xFF;
            result[6] = 0x0C;
            result[7] = 0x10;
            result[8] = Crc8(result, 8);
            return result;
        }

        private static byte Crc8(byte[] data, int count)
        {
            byte crc = 0;
            for(var i = 0; i < count; i++)
            {
                var inbyte = data[i];
                for(var bit = 0; bit < 8; bit++)
                {
                    var mix = (crc ^ inbyte) & 0x01;
                    crc >>= 1;
                    if(mix != 0)
                    {
                        crc ^= 0x8C;
                    }
                    inbyte >>= 1;
                }
            }
            return crc;
        }

        private void Enqueue(ulong delayUs, bool level)
        {
            events.Enqueue(new ScheduledLevel(delayUs, level));
        }

        private void ScheduleNext()
        {
            if(events.Count == 0)
            {
                return;
            }
            var next = events.Dequeue();
            nextLevel = next.Level;
            timer.Enabled = false;
            timer.Limit = Math.Max(1UL, next.DelayUs);
            timer.ResetValue();
            timer.Enabled = true;
        }

        private void OnTimer()
        {
            Data.Set(nextLevel);
            ScheduleNext();
        }

        private ulong NowUs()
        {
            return (ulong)machine.LocalTimeSource.ElapsedVirtualTime.TotalMicroseconds;
        }

        private const long TimerFrequency = 1000000;
        private const ulong ResetLowThresholdUs = 400;
        private const ulong WriteZeroThresholdUs = 45;

        private readonly IMachine machine;
        private readonly LimitTimer timer;
        private readonly Queue<ScheduledLevel> events = new Queue<ScheduledLevel>();
        private bool lastLevel;
        private bool nextLevel;
        private bool sendingScratchpad;
        private ulong lowStartedAt;
        private byte command;
        private int commandBits;
        private int sendBitIndex;
        private byte[] scratchpad = new byte[9];

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

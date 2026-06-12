//
// IoT-Bench deterministic DS1307 RTC model for Renode.
//
// Loaded at runtime via `include @.../DS1307.cs` before the platform
// description. Implements the read path of the DS1307 contract: a register
// pointer set by writes, BCD timekeeping registers 0x00-0x06 derived from a
// seeded wall-clock time plus elapsed virtual time, and 56 bytes of NVRAM.
// The benchmark contract is read-and-print (the prompt forbids setting the
// clock), so writes to the timekeeping registers are accepted but a write
// simply stores raw bytes that subsequent reads of NVRAM would see; the
// time registers always reflect the seeded clock, mirroring how the bench
// uses Wokwi's DS1307 (`initTime` attr, honored per simulation variant).
//
using System;
using System.Globalization;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.I2C;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.I2C
{
    public class IoTBench_DS1307 : II2CPeripheral
    {
        public IoTBench_DS1307(IMachine machine)
        {
            this.machine = machine;
            InitTime = "2000-01-01T00:00:00Z";
            Reset();
        }

        // Seed wall-clock, ISO-8601 (e.g. "2026-02-02T15:37:00Z"). Settable
        // from the platform description or per simulation variant from the
        // generated .resc before the run starts.
        public string InitTime
        {
            get => initTimeText;
            set
            {
                initTimeText = value;
                seedTime = DateTime.Parse(
                    value,
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);
                seedVirtualTime = machine.LocalTimeSource.ElapsedVirtualTime;
            }
        }

        public void Reset()
        {
            registerPointer = 0;
            pointerArmed = false;
        }

        public void Write(byte[] data)
        {
            if(data.Length == 0)
            {
                return;
            }
            registerPointer = (byte)(data[0] % RegisterCount);
            pointerArmed = true;
            for(var i = 1; i < data.Length; i++)
            {
                var target = (byte)((data[0] + i - 1) % RegisterCount);
                if(target >= TimekeepingRegisters)
                {
                    nvram[target - TimekeepingRegisters] = data[i];
                }
                // Writes into 0x00-0x06 are intentionally ignored: the
                // benchmark seeds the clock and validates the read path.
            }
        }

        public byte[] Read(int count = 1)
        {
            var result = new byte[count];
            for(var i = 0; i < count; i++)
            {
                result[i] = ReadRegister(registerPointer);
                registerPointer = (byte)((registerPointer + 1) % RegisterCount);
            }
            return result;
        }

        public void FinishTransmission()
        {
            pointerArmed = false;
        }

        private byte ReadRegister(byte offset)
        {
            if(offset >= TimekeepingRegisters)
            {
                return nvram[offset - TimekeepingRegisters];
            }
            var elapsed = machine.LocalTimeSource.ElapsedVirtualTime - seedVirtualTime;
            var now = seedTime + TimeSpan.FromTicks((long)(elapsed.TotalMicroseconds * 10));
            switch(offset)
            {
                case 0x00: return ToBcd(now.Second);             // CH bit 0 = oscillator on
                case 0x01: return ToBcd(now.Minute);
                case 0x02: return ToBcd(now.Hour);               // 24h mode (bit6 = 0)
                case 0x03: return ToBcd(((int)now.DayOfWeek) + 1);
                case 0x04: return ToBcd(now.Day);
                case 0x05: return ToBcd(now.Month);
                case 0x06: return ToBcd(now.Year % 100);
                default: return 0x00;                            // 0x07: control register
            }
        }

        private static byte ToBcd(int value)
        {
            return (byte)(((value / 10) << 4) | (value % 10));
        }

        private const int RegisterCount = 0x40;
        private const int TimekeepingRegisters = 0x08;

        private readonly IMachine machine;
        private readonly byte[] nvram = new byte[RegisterCount - TimekeepingRegisters];
        private string initTimeText;
        private DateTime seedTime;
        private TimeInterval seedVirtualTime;
        private byte registerPointer;
        private bool pointerArmed;
    }
}

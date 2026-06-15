//
// IoT-Bench deterministic nRF52840 SAADC model for Renode.
//
// Loaded at runtime via `include @.../NRF52840_SAADC.cs` before the platform
// description (the stock platforms/cpus/nrf52840.repl has no peripheral at
// 0x40007000). Implements the subset of the SAADC register contract that
// Zephyr's in-tree adc driver (adc_nrfx_saadc -> nrfx_saadc, simple
// non-blocking mode) exercises, verified against the nrfx 3.x sources:
//
//   1. CH[n].CONFIG / RESOLUTION / OVERSAMPLE / INTEN writes (mode set),
//   2. CH[n].PSELP / PSELN writes (channel activation; PSELP != 0 == active),
//   3. RESULT.PTR / RESULT.MAXCNT writes followed by TASKS_START
//      (nrfy_saadc_buffer_set with start trigger) -> EVENTS_STARTED + IRQ,
//   4. TASKS_SAMPLE (triggered from the STARTED irq handler) -> one 16-bit
//      sample per active channel written via EasyDMA to RESULT.PTR,
//      EVENTS_RESULTDONE / EVENTS_DONE per sample and EVENTS_END once
//      RESULT.MAXCNT samples were produced -> IRQ,
//   5. TASKS_STOP -> EVENTS_STOPPED (driver teardown), ENABLE = 0.
//
// Sample values are injected by the harness: each channel has a settable
// raw 12-bit count (0..4095) seeded from the generated .resc (fixture attrs
// and scenario set-control steps), mirroring how the bench drives Wokwi's
// potentiometer surrogate. Reads/writes of registers without modeled side
// effects fall through to a plain backing store so driver errata workarounds
// (e.g. nRF52 anomaly 212 scratch registers) stay silent and harmless.
//
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.Analog
{
    public class IoTBench_NRF52840_SAADC : IDoubleWordPeripheral, IKnownSize
    {
        public IoTBench_NRF52840_SAADC(IMachine machine)
        {
            this.machine = machine;
            IRQ = new GPIO();
            registers = new uint[RegisterSpaceSize / 4];
            channelValues = new uint[ChannelCount];
            Reset();
        }

        public void Reset()
        {
            Array.Clear(registers, 0, registers.Length);
            latchedPointer = 0;
            latchedMaxCount = 0;
            samplesWritten = 0;
            IRQ.Unset();
            // channelValues intentionally survive Reset: the harness seeds
            // them from the generated .resc before the run starts.
        }

        public long Size => RegisterSpaceSize;

        public GPIO IRQ { get; }

        // Raw 12-bit counts (0..4095) per SAADC channel, settable from the
        // monitor. At other resolutions the sample is rescaled accordingly.
        public uint Channel0Value { get { return channelValues[0]; } set { channelValues[0] = value; } }
        public uint Channel1Value { get { return channelValues[1]; } set { channelValues[1] = value; } }
        public uint Channel2Value { get { return channelValues[2]; } set { channelValues[2] = value; } }
        public uint Channel3Value { get { return channelValues[3]; } set { channelValues[3] = value; } }
        public uint Channel4Value { get { return channelValues[4]; } set { channelValues[4] = value; } }
        public uint Channel5Value { get { return channelValues[5]; } set { channelValues[5] = value; } }
        public uint Channel6Value { get { return channelValues[6]; } set { channelValues[6] = value; } }
        public uint Channel7Value { get { return channelValues[7]; } set { channelValues[7] = value; } }

        public void SetChannelValue(int channel, uint rawTwelveBit)
        {
            channelValues[channel] = rawTwelveBit;
        }

        public uint ReadDoubleWord(long offset)
        {
            switch(offset)
            {
                case IntenSet:
                case IntenClr:
                    return registers[Inten / 4];
                default:
                    return registers[offset / 4];
            }
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
                case TasksStart:
                    if(value != 0)
                    {
                        StartAcquisition();
                    }
                    break;
                case TasksSample:
                    if(value != 0)
                    {
                        Sample();
                    }
                    break;
                case TasksStop:
                    if(value != 0)
                    {
                        SetEventAndUpdate(EventsStopped);
                    }
                    break;
                case TasksCalibrateOffset:
                    if(value != 0)
                    {
                        SetEventAndUpdate(EventsCalibrateDone);
                    }
                    break;
                case Inten:
                    registers[Inten / 4] = value;
                    UpdateInterrupt();
                    break;
                case IntenSet:
                    registers[Inten / 4] |= value;
                    UpdateInterrupt();
                    break;
                case IntenClr:
                    registers[Inten / 4] &= ~value;
                    UpdateInterrupt();
                    break;
                default:
                    registers[offset / 4] = value;
                    if(offset >= EventsStarted && offset <= EventsLimitLast)
                    {
                        // Event registers are cleared by writing 0; the IRQ
                        // line follows (INTEN & pending events).
                        UpdateInterrupt();
                    }
                    break;
            }
        }

        private void StartAcquisition()
        {
            latchedPointer = registers[ResultPtr / 4];
            latchedMaxCount = registers[ResultMaxCnt / 4];
            samplesWritten = 0;
            SetEventAndUpdate(EventsStarted);
        }

        private void Sample()
        {
            if(registers[Enable / 4] == 0)
            {
                this.Log(LogLevel.Warning, "TASKS_SAMPLE triggered while the SAADC is disabled; ignoring");
                return;
            }
            var wroteAny = false;
            for(var channel = 0; channel < ChannelCount && samplesWritten < latchedMaxCount; channel++)
            {
                if(registers[(Ch0PselP + channel * ChannelStride) / 4] == PselDisabled)
                {
                    continue;
                }
                var sample = ScaleToResolution(channelValues[channel]);
                machine.GetSystemBus(this).WriteWord(latchedPointer + 2ul * samplesWritten, (ushort)sample);
                samplesWritten++;
                wroteAny = true;
                registers[EventsResultDone / 4] = 1;
            }
            if(wroteAny)
            {
                registers[EventsDone / 4] = 1;
            }
            if(latchedMaxCount > 0 && samplesWritten >= latchedMaxCount)
            {
                registers[ResultAmount / 4] = samplesWritten;
                registers[EventsEnd / 4] = 1;
            }
            UpdateInterrupt();
        }

        private uint ScaleToResolution(uint rawTwelveBit)
        {
            // RESOLUTION VAL: 0 = 8 bit, 1 = 10 bit, 2 = 12 bit, 3 = 14 bit.
            switch(registers[Resolution / 4] & 0x7)
            {
                case 0:
                    return rawTwelveBit >> 4;
                case 1:
                    return rawTwelveBit >> 2;
                case 3:
                    return rawTwelveBit << 2;
                default:
                    return rawTwelveBit;
            }
        }

        private void SetEventAndUpdate(long eventOffset)
        {
            registers[eventOffset / 4] = 1;
            UpdateInterrupt();
        }

        private void UpdateInterrupt()
        {
            // INTEN bit n corresponds to the event register at 0x100 + 4*n
            // (STARTED, END, DONE, RESULTDONE, CALIBRATEDONE, STOPPED, then
            // the CH[n].LIMITH/LIMITL pairs).
            var inten = registers[Inten / 4];
            var pending = false;
            for(var bit = 0; bit < EventCount; bit++)
            {
                if((inten & (1u << bit)) == 0)
                {
                    continue;
                }
                if(registers[(EventsStarted + 4 * bit) / 4] != 0)
                {
                    pending = true;
                    break;
                }
            }
            IRQ.Set(pending);
        }

        private const long RegisterSpaceSize = 0x1000;
        private const int ChannelCount = 8;
        private const int ChannelStride = 0x10;
        private const int EventCount = 22; // 6 core events + 8 channels * 2 limit events
        private const uint PselDisabled = 0; // PSELP "NC"

        private const long TasksStart = 0x000;
        private const long TasksSample = 0x004;
        private const long TasksStop = 0x008;
        private const long TasksCalibrateOffset = 0x00C;
        private const long EventsStarted = 0x100;
        private const long EventsEnd = 0x104;
        private const long EventsDone = 0x108;
        private const long EventsResultDone = 0x10C;
        private const long EventsCalibrateDone = 0x110;
        private const long EventsStopped = 0x114;
        private const long EventsLimitLast = 0x154; // CH[7].LIMITL
        private const long Inten = 0x300;
        private const long IntenSet = 0x304;
        private const long IntenClr = 0x308;
        private const long Enable = 0x500;
        private const long Ch0PselP = 0x510;
        private const long Resolution = 0x5F0;
        private const long ResultPtr = 0x62C;
        private const long ResultMaxCnt = 0x630;
        private const long ResultAmount = 0x634;

        private readonly IMachine machine;
        private readonly uint[] registers;
        private readonly uint[] channelValues;
        private uint latchedPointer;
        private uint latchedMaxCount;
        private uint samplesWritten;
    }
}

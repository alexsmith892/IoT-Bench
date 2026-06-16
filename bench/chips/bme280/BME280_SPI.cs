//
// IoT-Bench deterministic BME280 SPI model for Renode.
//
// Register-level BME280 subset for benchmark use: chip ID, calibration
// registers, control register writes, and measurement registers for
// temperature/humidity. SPI transactions use the BME280 command byte semantics
// (bit 7 = read, bits 6..0 = register address).
//
using System;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.SPI
{
    public class IoTBench_BME280_SPI : ISPIPeripheral
    {
        public IoTBench_BME280_SPI()
        {
            Temperature = 24.5m;
            Humidity = 55m;
            Reset();
        }

        public decimal Temperature { get; set; }
        public decimal Humidity { get; set; }

        public void Reset()
        {
            Array.Clear(registers, 0, registers.Length);
            LoadCalibration();
            registers[0xD0] = 0x60;
            registers[0xF2] = 0;
            registers[0xF3] = 0;
            registers[0xF4] = 0;
            registers[0xF5] = 0;
            commandSeen = false;
            reading = false;
            registerPointer = 0;
        }

        public byte Transmit(byte data)
        {
            if(!commandSeen || (reading && IsCommandByte(data)))
            {
                StartCommand(data);
                return 0xFF;
            }
            if(reading)
            {
                var value = ReadRegister(registerPointer);
                registerPointer++;
                return value;
            }
            WriteRegister(registerPointer, data);
            registerPointer++;
            commandSeen = false;
            reading = false;
            return 0xFF;
        }

        public void FinishTransmission()
        {
            commandSeen = false;
            reading = false;
        }

        private byte ReadRegister(byte offset)
        {
            offset = CanonicalRegister(offset);
            if(offset >= 0xF7 && offset <= 0xFE)
            {
                UpdateMeasurementRegisters();
            }
            return registers[offset];
        }

        private void WriteRegister(byte offset, byte value)
        {
            offset = CanonicalRegister(offset);
            switch(offset)
            {
                case 0xE0:
                    if(value == 0xB6)
                    {
                        Reset();
                    }
                    break;
                case 0xF2:
                case 0xF4:
                case 0xF5:
                    registers[offset] = value;
                    break;
            }
        }

        private void StartCommand(byte data)
        {
            commandSeen = true;
            reading = (data & 0x80) != 0;
            registerPointer = (byte)(data & 0x7F);
        }

        private static bool IsCommandByte(byte data)
        {
            var offset = CanonicalRegister((byte)(data & 0x7F));
            return (offset >= 0x88 && offset <= 0xA1) ||
                offset == 0xD0 ||
                offset == 0xE0 ||
                (offset >= 0xE1 && offset <= 0xE7) ||
                (offset >= 0xF2 && offset <= 0xF5) ||
                (offset >= 0xF7 && offset <= 0xFE);
        }

        private static byte CanonicalRegister(byte offset)
        {
            // SPI transfers clear bit 7 for writes and commonly send
            // register|0x80 for reads. Mirror the documented BME280 register
            // map into the 7-bit SPI address window used on the wire.
            if(offset >= 0x08 && offset <= 0x21)
            {
                return (byte)(offset + 0x80);
            }
            if(offset >= 0x50 && offset <= 0x7E)
            {
                return (byte)(offset + 0x80);
            }
            return offset;
        }

        private void LoadCalibration()
        {
            PutU16(0x88, DigT1);
            PutS16(0x8A, DigT2);
            PutS16(0x8C, DigT3);
            PutU16(0x8E, DigP1);
            PutS16(0x90, DigP2);
            PutS16(0x92, DigP3);
            PutS16(0x94, DigP4);
            PutS16(0x96, DigP5);
            PutS16(0x98, DigP6);
            PutS16(0x9A, DigP7);
            PutS16(0x9C, DigP8);
            PutS16(0x9E, DigP9);
            registers[0xA1] = DigH1;
            PutS16(0xE1, DigH2);
            registers[0xE3] = DigH3;
            registers[0xE4] = (byte)(DigH4 >> 4);
            registers[0xE5] = (byte)(((DigH5 & 0x0F) << 4) | (DigH4 & 0x0F));
            registers[0xE6] = (byte)(DigH5 >> 4);
            registers[0xE7] = unchecked((byte)DigH6);
        }

        private void UpdateMeasurementRegisters()
        {
            var humidity = Humidity;
            if(humidity < 0m) humidity = 0m;
            if(humidity > 100m) humidity = 100m;

            int tFine;
            var adcT = InvertTemperature(Temperature, out tFine);
            var adcH = InvertHumidity(humidity, tFine);
            var adcP = 415148; // pressure is not part of the Zephyr SPI oracle

            registers[0xF7] = (byte)(adcP >> 12);
            registers[0xF8] = (byte)(adcP >> 4);
            registers[0xF9] = (byte)((adcP & 0x0F) << 4);
            registers[0xFA] = (byte)(adcT >> 12);
            registers[0xFB] = (byte)(adcT >> 4);
            registers[0xFC] = (byte)((adcT & 0x0F) << 4);
            registers[0xFD] = (byte)(adcH >> 8);
            registers[0xFE] = (byte)adcH;
        }

        private static int CompensateTemperature(int adcT, out int tFine)
        {
            var var1 = ((((adcT >> 3) - (DigT1 << 1))) * DigT2) >> 11;
            var var2 = (((((adcT >> 4) - DigT1) * ((adcT >> 4) - DigT1)) >> 12) * DigT3) >> 14;
            tFine = var1 + var2;
            return (tFine * 5 + 128) >> 8;
        }

        private static uint CompensateHumidity(int adcH, int tFine)
        {
            var v = tFine - 76800;
            v = (((((adcH << 14) - (DigH4 << 20) - (DigH5 * v)) + 16384) >> 15) *
                (((((((v * DigH6) >> 10) * (((v * DigH3) >> 11) + 32768)) >> 10) + 2097152) *
                DigH2 + 8192) >> 14));
            v -= (((((v >> 15) * (v >> 15)) >> 7) * DigH1) >> 4);
            if(v < 0) v = 0;
            if(v > 419430400) v = 419430400;
            return (uint)(v >> 12);
        }

        private static uint InvertTemperature(decimal targetC, out int tFine)
        {
            var target = (int)Math.Round(targetC * 100m);
            uint lo = 0;
            uint hi = 1048575;
            for(var i = 0; i < 24; i++)
            {
                var mid = (lo + hi) / 2;
                int midFine;
                var actual = CompensateTemperature((int)mid, out midFine);
                if(actual < target)
                {
                    lo = mid + 1;
                }
                else
                {
                    hi = mid;
                }
            }
            var best = lo;
            int bestFine;
            var bestTemp = CompensateTemperature((int)best, out bestFine);
            var start = lo > 8 ? lo - 8 : 0;
            var end = lo + 8 > 1048575 ? 1048575 : lo + 8;
            for(var raw = start; raw <= end; raw++)
            {
                int rawFine;
                var actual = CompensateTemperature((int)raw, out rawFine);
                if(Math.Abs(actual - target) < Math.Abs(bestTemp - target))
                {
                    best = raw;
                    bestTemp = actual;
                    bestFine = rawFine;
                }
            }
            tFine = bestFine;
            return best;
        }

        private static uint InvertHumidity(decimal targetRh, int tFine)
        {
            var target = (uint)Math.Round(targetRh * 1024m);
            uint lo = 0;
            uint hi = 65535;
            for(var i = 0; i < 20; i++)
            {
                var mid = (lo + hi) / 2;
                var actual = CompensateHumidity((int)mid, tFine);
                if(actual < target)
                {
                    lo = mid + 1;
                }
                else
                {
                    hi = mid;
                }
            }
            var best = lo;
            var bestH = CompensateHumidity((int)best, tFine);
            var start = lo > 16 ? lo - 16 : 0;
            var end = lo + 16 > 65535 ? 65535 : lo + 16;
            for(var raw = start; raw <= end; raw++)
            {
                var actual = CompensateHumidity((int)raw, tFine);
                if(Math.Abs((int)actual - (int)target) < Math.Abs((int)bestH - (int)target))
                {
                    best = raw;
                    bestH = actual;
                }
            }
            return best;
        }

        private void PutU16(byte offset, ushort value)
        {
            registers[offset] = (byte)(value & 0xFF);
            registers[offset + 1] = (byte)(value >> 8);
        }

        private void PutS16(byte offset, short value)
        {
            PutU16(offset, unchecked((ushort)value));
        }

        private readonly byte[] registers = new byte[256];
        private bool commandSeen;
        private bool reading;
        private byte registerPointer;

        private const ushort DigT1 = 27504;
        private const short DigT2 = 26435;
        private const short DigT3 = -1000;
        private const ushort DigP1 = 36477;
        private const short DigP2 = -10685;
        private const short DigP3 = 3024;
        private const short DigP4 = 2855;
        private const short DigP5 = 140;
        private const short DigP6 = -7;
        private const short DigP7 = 15500;
        private const short DigP8 = -14600;
        private const short DigP9 = 6000;
        private const byte DigH1 = 75;
        private const short DigH2 = 362;
        private const byte DigH3 = 0;
        private const short DigH4 = 325;
        private const short DigH5 = 50;
        private const sbyte DigH6 = 30;
    }
}

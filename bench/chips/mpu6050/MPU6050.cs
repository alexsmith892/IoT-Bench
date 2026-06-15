//
// IoT-Bench deterministic MPU6050 IMU model for Renode.
//
// Loaded at runtime via `include @.../MPU6050.cs` before the platform
// description. Implements the register-level read path of the benchmark
// contract: a register pointer set by writes, big-endian 16-bit sensor
// output registers 0x3B..0x48 derived from scenario-settable physical
// values, WHO_AM_I, and plain byte storage for configuration registers
// (PWR_MGMT_1 wake-up, sample rate, etc.). The register pointer survives
// FinishTransmission so both separate write/read transactions and combined
// transfers address the same register map.
//
// Sensitivities follow the datasheet full-scale selections and honor
// ACCEL_CONFIG/GYRO_CONFIG written by firmware: accel 16384 LSB/g at +/-2 g
// (halved per FS step), gyro 131 LSB/(deg/s) at +/-250 dps. The benchmark
// oracles assume the power-on defaults, same as the Wokwi MPU6050 tasks.
//
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.I2C;

namespace Antmicro.Renode.Peripherals.I2C
{
    public class IoTBench_MPU6050 : II2CPeripheral
    {
        public IoTBench_MPU6050(IMachine machine)
        {
            this.machine = machine;
            AccelerationX = 0m;
            AccelerationY = 0m;
            AccelerationZ = 1m;
            AngularRateX = 0m;
            AngularRateY = 0m;
            AngularRateZ = 0m;
            Temperature = 25m;
            Reset();
        }

        // Physical values, settable from the platform description or per
        // simulation variant / scenario step from the generated .resc.
        public decimal AccelerationX { get; set; } // g
        public decimal AccelerationY { get; set; }
        public decimal AccelerationZ { get; set; }
        public decimal AngularRateX { get; set; } // deg/s
        public decimal AngularRateY { get; set; }
        public decimal AngularRateZ { get; set; }
        public decimal Temperature { get; set; }  // degrees C

        public void Reset()
        {
            Array.Clear(registers, 0, registers.Length);
            registers[PwrMgmt1] = 0x40; // power-on default: SLEEP=1
            registerPointer = 0;
        }

        public void Write(byte[] data)
        {
            if(data.Length == 0)
            {
                return;
            }
            registerPointer = data[0];
            for(var i = 1; i < data.Length; i++)
            {
                WriteRegister((byte)(data[0] + i - 1), data[i]);
            }
        }

        public byte[] Read(int count = 1)
        {
            var result = new byte[count];
            for(var i = 0; i < count; i++)
            {
                result[i] = ReadRegister(registerPointer);
                registerPointer = (byte)(registerPointer + 1);
            }
            return result;
        }

        public void FinishTransmission()
        {
            // The register pointer persists across STOP, matching the real
            // device's burst-read behavior after a separate address write.
        }

        private void WriteRegister(byte offset, byte value)
        {
            if(offset == PwrMgmt1 && (value & 0x80) != 0)
            {
                Reset();
                return;
            }
            registers[offset] = value;
        }

        private byte ReadRegister(byte offset)
        {
            switch(offset)
            {
                case 0x3B: return High(AccelRaw(AccelerationX));
                case 0x3C: return Low(AccelRaw(AccelerationX));
                case 0x3D: return High(AccelRaw(AccelerationY));
                case 0x3E: return Low(AccelRaw(AccelerationY));
                case 0x3F: return High(AccelRaw(AccelerationZ));
                case 0x40: return Low(AccelRaw(AccelerationZ));
                case 0x41: return High(TempRaw());
                case 0x42: return Low(TempRaw());
                case 0x43: return High(GyroRaw(AngularRateX));
                case 0x44: return Low(GyroRaw(AngularRateX));
                case 0x45: return High(GyroRaw(AngularRateY));
                case 0x46: return Low(GyroRaw(AngularRateY));
                case 0x47: return High(GyroRaw(AngularRateZ));
                case 0x48: return Low(GyroRaw(AngularRateZ));
                case WhoAmI: return 0x68;
                default: return registers[offset];
            }
        }

        private short AccelRaw(decimal g)
        {
            // AFS_SEL halves the sensitivity per step: 16384/8192/4096/2048.
            var fs = (registers[AccelConfig] >> 3) & 0x3;
            return Saturate(g * (16384m / (1 << fs)));
        }

        private short GyroRaw(decimal dps)
        {
            // FS_SEL: 131/65.5/32.8/16.4 LSB/(deg/s).
            var fs = (registers[GyroConfig] >> 3) & 0x3;
            return Saturate(dps * 131m / (1 << fs));
        }

        private short TempRaw()
        {
            // Datasheet: TEMP_degC = TEMP_OUT/340 + 36.53
            return Saturate((Temperature - 36.53m) * 340m);
        }

        private static short Saturate(decimal value)
        {
            if(value > short.MaxValue)
            {
                return short.MaxValue;
            }
            if(value < short.MinValue)
            {
                return short.MinValue;
            }
            return (short)Math.Round(value);
        }

        private static byte High(short value) => (byte)((value >> 8) & 0xFF);
        private static byte Low(short value) => (byte)(value & 0xFF);

        private const byte GyroConfig = 0x1B;
        private const byte AccelConfig = 0x1C;
        private const byte PwrMgmt1 = 0x6B;
        private const byte WhoAmI = 0x75;

        private readonly IMachine machine;
        private readonly byte[] registers = new byte[256];
        private byte registerPointer;
    }
}

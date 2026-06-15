//
// IoT-Bench deterministic 4x4 matrix keypad model for Renode.
//
// Loaded at runtime via `include @.../MatrixKeypad.cs` before the platform
// description. Models the electrical cross-point matrix the same way the
// bench's Wokwi fixture does with per-key matrix_key switches: the firmware
// drives the ROW lines as outputs (active-low scan) and reads the COLUMN
// lines; while key (r, c) is held and row r is driven LOW, column c reads
// LOW, otherwise columns idle HIGH.
//
// Wiring (generated .repl):
//   - row levels arrive as GPIO inputs 0..3 (`gpioX: { pin -> keypad0@r }`),
//   - column outputs 0..3 drive the column pins (`r -> gpioX@pin` via the
//     numbered Connections),
//   - key state is set from the generated .resc / scenario steps with
//     `keypad0 PressKey r c` / `keypad0 ReleaseKey r c`.
//
// The model is registered on the system bus at an unused address purely so
// it has a monitor name; its register window is inert (reads 0). Multi-key
// ghosting is not modeled (bench scenarios press one key at a time).
//
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class IoTBench_MatrixKeypad : IDoubleWordPeripheral, IKnownSize, IGPIOReceiver, INumberedGPIOOutput
    {
        public IoTBench_MatrixKeypad()
        {
            var connections = new Dictionary<int, IGPIO>();
            for(var i = 0; i < Size4; i++)
            {
                connections[i] = new GPIO();
            }
            Connections = new ReadOnlyDictionary<int, IGPIO>(connections);
            Reset();
        }

        public void Reset()
        {
            Array.Clear(pressed, 0, pressed.Length);
            for(var i = 0; i < Size4; i++)
            {
                // Idle: no scan active (rows high), columns pulled high.
                rowLevels[i] = true;
                Connections[i].Set(true);
            }
        }

        public long Size => 0x1000;

        public IReadOnlyDictionary<int, IGPIO> Connections { get; }

        // Row levels driven by the firmware arrive here (input r = row r).
        public void OnGPIO(int number, bool value)
        {
            if(number < 0 || number >= Size4)
            {
                this.Log(LogLevel.Warning, "Keypad row input {0} out of range", number);
                return;
            }
            rowLevels[number] = value;
            RecomputeColumns();
        }

        public void PressKey(int row, int column)
        {
            SetKey(row, column, true);
        }

        public void ReleaseKey(int row, int column)
        {
            SetKey(row, column, false);
        }

        public void SetKey(int row, int column, bool isPressed)
        {
            if(row < 0 || row >= Size4 || column < 0 || column >= Size4)
            {
                this.Log(LogLevel.Warning, "Keypad key ({0}, {1}) out of range", row, column);
                return;
            }
            pressed[row, column] = isPressed;
            RecomputeColumns();
        }

        public uint ReadDoubleWord(long offset)
        {
            return 0;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            // Inert register window: the keypad is GPIO-only; the sysbus
            // mapping exists to give the model a monitor name.
        }

        private void RecomputeColumns()
        {
            for(var c = 0; c < Size4; c++)
            {
                var low = false;
                for(var r = 0; r < Size4; r++)
                {
                    if(pressed[r, c] && !rowLevels[r])
                    {
                        low = true;
                        break;
                    }
                }
                Connections[c].Set(!low);
            }
        }

        private const int Size4 = 4;

        private readonly bool[,] pressed = new bool[Size4, Size4];
        private readonly bool[] rowLevels = new bool[Size4];
    }
}

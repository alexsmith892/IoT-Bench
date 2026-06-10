# Deterministic BME280 Custom Chip

This chip is built locally for IoT-Bench instead of vendoring the public
`bonnyr/wokwi-bme280-custom-chip` binary. That project has a prebuilt release,
but its documented model uses prerecorded sample sets and was SPI-only at the
time it was evaluated, which does not satisfy IoT-Bench's scenario attrs or I2C
requirements.

Build command:

```powershell
wokwi-cli chip compile bench\chips\bme280\bme280.chip.c -o cases\bme280-read-i2c-wokwi-mega\chips\bme280.chip.wasm
Copy-Item cases\bme280-read-i2c-wokwi-mega\chips\bme280.chip.wasm cases\bme280-read-spi-wokwi-mega\chips\bme280.chip.wasm -Force
Copy-Item bench\chips\bme280\bme280.chip.json cases\bme280-read-i2c-wokwi-mega\chips\bme280.chip.json -Force
Copy-Item bench\chips\bme280\bme280.chip.json cases\bme280-read-spi-wokwi-mega\chips\bme280.chip.json -Force
```

The chip exposes `temperatureC`, `humidityRH`, and `pressurePa` attrs. It uses
fixed BME280 calibration coefficients and converts the attr values into raw ADC
registers by inverse-searching the same compensation formulas used by common
Arduino libraries. Run `python bench\chips\bme280\derive_raw.py` to audit the
scenario raw values.

Supported protocol surface:

- I2C on addresses `0x76` and `0x77`
- GPIO-level software SPI on `SCK`, `SDI`, `SDO`, `CS`
- Chip ID, reset, calibration, control/status/config, and ADC data registers

This is a deterministic benchmark peripheral, not a full physical emulator.

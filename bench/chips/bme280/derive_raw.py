"""Audit helper for the deterministic BME280 custom chip.

The custom chip exposes final scenario values as Wokwi attrs, but common
Arduino libraries read raw ADC registers and run Bosch compensation formulas.
This script mirrors the fixed calibration and inverse-search logic embedded in
``bme280.chip.c`` so expected raw values are easy to inspect.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Calibration:
    dig_T1: int = 27504
    dig_T2: int = 26435
    dig_T3: int = -1000
    dig_P1: int = 36477
    dig_P2: int = -10685
    dig_P3: int = 3024
    dig_P4: int = 2855
    dig_P5: int = 140
    dig_P6: int = -7
    dig_P7: int = 15500
    dig_P8: int = -14600
    dig_P9: int = 6000
    dig_H1: int = 75
    dig_H2: int = 362
    dig_H3: int = 0
    dig_H4: int = 325
    dig_H5: int = 50
    dig_H6: int = 30


CAL = Calibration()


def compensate_temperature(adc_t: int, cal: Calibration = CAL) -> tuple[float, int]:
    var1 = (((adc_t >> 3) - (cal.dig_T1 << 1)) * cal.dig_T2) >> 11
    var2 = (((((adc_t >> 4) - cal.dig_T1) * ((adc_t >> 4) - cal.dig_T1)) >> 12) * cal.dig_T3) >> 14
    t_fine = var1 + var2
    temp_c = ((t_fine * 5 + 128) >> 8) / 100.0
    return temp_c, t_fine


def compensate_humidity(adc_h: int, t_fine: int, cal: Calibration = CAL) -> float:
    value = t_fine - 76800
    value = (
        (((adc_h << 14) - (cal.dig_H4 << 20) - (cal.dig_H5 * value) + 16384) >> 15)
        * (
            (((((((value * cal.dig_H6) >> 10) * (((value * cal.dig_H3) >> 11) + 32768)) >> 10) + 2097152)
              * cal.dig_H2
              + 8192)
             >> 14)
        )
    )
    value = value - (((((value >> 15) * (value >> 15)) >> 7) * cal.dig_H1) >> 4)
    value = max(0, min(value, 419430400))
    return (value >> 12) / 1024.0


def compensate_pressure(adc_p: int, t_fine: int, cal: Calibration = CAL) -> float:
    var1 = t_fine - 128000
    var2 = var1 * var1 * cal.dig_P6
    var2 = var2 + ((var1 * cal.dig_P5) << 17)
    var2 = var2 + (cal.dig_P4 << 35)
    var1 = ((var1 * var1 * cal.dig_P3) >> 8) + ((var1 * cal.dig_P2) << 12)
    var1 = (((1 << 47) + var1) * cal.dig_P1) >> 33
    if var1 == 0:
        return 0.0
    p = 1048576 - adc_p
    p = (((p << 31) - var2) * 3125) // var1
    var1 = (cal.dig_P9 * (p >> 13) * (p >> 13)) >> 25
    var2 = (cal.dig_P8 * p) >> 19
    p = ((p + var1 + var2) >> 8) + (cal.dig_P7 << 4)
    return p / 256.0


def invert_temperature(target_c: float) -> tuple[int, float, int]:
    lo, hi = 0, 1048575
    for _ in range(24):
        mid = (lo + hi) // 2
        actual, _ = compensate_temperature(mid)
        if actual < target_c:
            lo = mid + 1
        else:
            hi = mid
    best = min(range(max(0, lo - 4), min(1048575, lo + 4) + 1), key=lambda raw: abs(compensate_temperature(raw)[0] - target_c))
    actual, t_fine = compensate_temperature(best)
    return best, actual, t_fine


def invert_humidity(target_rh: float, t_fine: int) -> tuple[int, float]:
    lo, hi = 0, 65535
    for _ in range(20):
        mid = (lo + hi) // 2
        if compensate_humidity(mid, t_fine) < target_rh:
            lo = mid + 1
        else:
            hi = mid
    best = min(range(max(0, lo - 8), min(65535, lo + 8) + 1), key=lambda raw: abs(compensate_humidity(raw, t_fine) - target_rh))
    return best, compensate_humidity(best, t_fine)


def invert_pressure(target_pa: float, t_fine: int) -> tuple[int, float]:
    lo, hi = 0, 1048575
    for _ in range(24):
        mid = (lo + hi) // 2
        actual = compensate_pressure(mid, t_fine)
        if actual > target_pa:
            lo = mid + 1
        else:
            hi = mid
    best = min(range(max(0, lo - 8), min(1048575, lo + 8) + 1), key=lambda raw: abs(compensate_pressure(raw, t_fine) - target_pa))
    return best, compensate_pressure(best, t_fine)


def derive(temperature_c: float, humidity_rh: float, pressure_pa: float = 101325.0) -> dict[str, float | int]:
    raw_t, actual_t, t_fine = invert_temperature(temperature_c)
    raw_h, actual_h = invert_humidity(humidity_rh, t_fine)
    raw_p, actual_p = invert_pressure(pressure_pa, t_fine)
    return {
        "adc_T": raw_t,
        "temperatureC": actual_t,
        "t_fine": t_fine,
        "adc_H": raw_h,
        "humidityRH": actual_h,
        "adc_P": raw_p,
        "pressurePa": actual_p,
    }


if __name__ == "__main__":
    for temp, humidity in ((24.5, 55.0), (31.0, 42.0)):
        print(f"{temp:.1f} C / {humidity:.1f}% RH -> {derive(temp, humidity)}")

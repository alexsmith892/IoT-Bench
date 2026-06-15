# Contributing

Thanks for taking a look at IoT-Bench. Generated build and simulation outputs
should be reproducible on each machine instead of committed with local paths.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m bench.cli doctor
```

Offline tests should pass without Wokwi credentials:

```powershell
python -m unittest discover tests
```

Live integration (opt-in) needs platform-specific tools:

- **Arduino Mega / ESP32-S3**: `wokwi-cli`, network, `WOKWI_CLI_TOKEN`; plus
  `arduino-cli` (Mega) or `idf.py` (ESP32-S3).
- **Zephyr / Renode**: Renode, Zephyr `west` workspace, cmake, ninja. Check with
  `python -m bench.cli doctor --platform zephyr_nano33ble`. Override paths with
  `IOTBENCH_RENODE`, `IOTBENCH_WEST`, `ZEPHYR_WORKSPACE`.

```powershell
$env:RUN_WOKWI_INTEGRATION = "1"
python -m unittest discover tests
```

## Generated files

Do not commit build outputs or run artifacts. Everything under
`cases/*/artifacts/` is generated except:

- `cases/*/artifacts/variants/*/diagram.json` (Wokwi variant fixtures)
- `cases/*/artifacts/variants/*/case.repl` (Renode variant platform descriptions)

These variant files are deterministic derived inputs for provenance and
`--use-existing-artifacts` validation.

Also gitignored: `cases/*/sketch/*/build/`, `cases/*/case.resc` (embeds absolute
paths; regenerated on each simulate), `cases/*/*.vcd`, ESP-IDF `sdkconfig*`.

Regenerate with `python -m bench.cli generate`, `build`, or `run`.
`tests/test_repo_hygiene.py` enforces this in CI.

# Contributing

Thanks for taking a look at IoT-Bench. The repository is meant to stay portable:
generated Arduino and Wokwi outputs should be reproducible on each contributor's
machine instead of committed with local paths.

## Local Setup

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

Live Arduino Mega Wokwi runs require `arduino-cli`, `wokwi-cli`, the Arduino
AVR platform, network access, and `WOKWI_CLI_TOKEN`. ESP32-S3 ESP-IDF Wokwi
runs require `idf.py`, `wokwi-cli`, network access, and `WOKWI_CLI_TOKEN`.
Zephyr/Nano 33 BLE Renode runs require Renode, a Zephyr `west` workspace
with the SDK installed, and cmake/ninja; check them with
`python -m bench.cli doctor --platform zephyr_nano33ble` (the harness finds
Renode and the workspace's venv `west` in their default locations, or set
`IOTBENCH_RENODE`, `IOTBENCH_WEST`, and `ZEPHYR_WORKSPACE`).

## Generated Files

Do not commit build outputs or run artifacts from these locations:

```text
artifacts/build/
artifacts/logic/*.vcd
artifacts/serial/*.log
artifacts/archive/
artifacts/submissions/
artifacts/variants/
artifacts/verification.json
cases/*/artifacts/build/
cases/*/artifacts/logic/*.vcd
cases/*/artifacts/serial/*.log
cases/*/artifacts/archive/
cases/*/artifacts/submissions/
cases/*/artifacts/variants/   (except diagram.json, see below)
cases/*/artifacts/verification.json
cases/*/sketch/*/build/
cases/*/*.vcd
cases/*/case.resc
```

Those files often contain absolute paths to the local Arduino installation or
workspace. Regenerate cases and artifacts with `python -m bench.cli generate`,
`python -m bench.cli build`, or `python -m bench.cli run`.

Two exceptions are committed deliberately:
`cases/*/artifacts/variants/*/diagram.json` (Wokwi) and
`cases/*/artifacts/variants/*/case.repl` (Renode). Variant diagrams and
platform descriptions are deterministic derived inputs that the verification
manifest and `--use-existing-artifacts` validation read, so they stay tracked
and reviewable. Renode `case.resc` scripts are NOT tracked anywhere: they
embed absolute output paths (Renode resolves write-paths against its own
working directory) and are re-emitted deterministically on every simulate.
`tests/test_repo_hygiene.py` enforces all of this.

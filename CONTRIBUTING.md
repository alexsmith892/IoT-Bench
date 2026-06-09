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

Live Wokwi runs require `arduino-cli`, `wokwi-cli`, the Arduino AVR platform,
network access, and `WOKWI_CLI_TOKEN`.

## Generated Files

Do not commit build outputs or run artifacts from these locations:

```text
artifacts/build/
artifacts/logic/*.vcd
artifacts/serial/*.log
artifacts/archive/
artifacts/verification.json
cases/*/artifacts/build/
cases/*/artifacts/logic/*.vcd
cases/*/artifacts/serial/*.log
cases/*/artifacts/archive/
cases/*/artifacts/verification.json
cases/*/sketch/*/build/
cases/*/*.vcd
```

Those files often contain absolute paths to the local Arduino installation or
workspace. Regenerate cases and artifacts with `python -m bench.cli generate`,
`python -m bench.cli build`, or `python -m bench.cli run`.

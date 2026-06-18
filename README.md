# IoT-Bench

Benchmark infrastructure for evaluating LLM-generated embedded firmware. Give a
model a task prompt, submit the code it writes, and the harness builds it,
runs it in a simulator, and judges behavior against hardcode-resistant oracles.

The goal is a reproducible benchmark across embedded platforms, with
leaderboard orchestration for model-generated firmware - not a one-off test
suite. The current leaderboard path is token-only and produces local run
reports; a public UI, published results tree, fault injection, and waveform
analysis beyond what validators already do are future work unless you see them
in the code.

## Platforms

| Platform | Board | Build | Simulator |
|---|---|---|---|
| `arduino_mega` | Arduino Mega (AVR) | arduino-cli | Wokwi |
| `esp32s3_espidf` | ESP32-S3 DevKitC | idf.py (ESP-IDF) | Wokwi |
| `zephyr_nano33ble` | Arduino Nano 33 BLE | west (Zephyr) | Renode (headless) |

Each platform has its own build output format and simulator. Arduino cases use
`.ino` sketches; ESP-IDF cases are CMake projects; Zephyr cases are a single
`src/main.c` with harness-owned `CMakeLists.txt` / `prj.conf`.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m bench.cli doctor
```

Check other platforms:

```powershell
python -m bench.cli doctor --platform esp32s3_espidf
python -m bench.cli doctor --platform zephyr_nano33ble
```

Run one task end to end:

```powershell
python -m bench.cli prompt --task blink_led_1hz    # what a model may see
python -m bench.cli generate --task blink_led_1hz
python -m bench.cli build --task blink_led_1hz
python -m bench.cli run --task blink_led_1hz
```

Evaluate a folder of submitted sketches:

```powershell
python -m bench.cli evaluate --sketch-dir path/to/submissions --output results.jsonl
```

Plan a leaderboard run without model spend:

```powershell
python -m bench.leaderboard plan --benchmark iot_skillsbench_v1 --platform arduino_mega --limit 3
```

Offline tests (no Wokwi token or network):

```powershell
python -m unittest discover tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup details, what not to commit, and
live integration requirements.

## How tasks work

Each task has two sides:

- **Prompt** (`tasks/<platform>/levelN/<task>.prompt.md`) - frozen spec shown to
  the model. Print it with `python -m bench.cli prompt --task <id>`.
- **YAML** (`tasks/<platform>/levelN/<task>.yaml`) - the answer key: variant
  stimulus, scenario timings, expected bands. Never show this to a model under
  test.

The harness generates a simulator project under `cases/`, compiles the firmware,
runs simulation, and writes a result. Top-level outcome codes:

| Code | Meaning |
|---|---|
| `BC` | Built and behavior passed |
| `BF` | Built but behavior failed |
| `CF` | Submission's own source failed to compile |
| `IF` | Inconclusive (simulator, environment, harness, or bad artifacts - retry, don't score) |

Detailed JSON includes `failure_stage`, `failure_source`, and `metrics` for
debugging.

Oracles are designed so hardcoded output fails: simulation variants, stimulus
correlation, static source gates, and an adversarial cheat-stub corpus in
`tests/adversarial/`. See `docs/` for platform-specific maturity notes.

## Repository layout

```text
bench/           Harness: CLI, generation, build, simulation, validators
bench/leaderboard/ Token-only leaderboard orchestration, providers, reports
tasks/           Task prompts and YAML oracles (127 tasks, 3 platforms)
cases/           Generated simulator projects + reference sketches
benchmarks/      Leaderboard manifests and skill packs
tests/           Offline regression suite and adversarial stubs
docs/            Platform status and design notes (tracked)
```

Build products, VCD captures, serial logs, and verification manifests live under
`cases/<case>/artifacts/` and are gitignored except variant `diagram.json` /
`case.repl` files (deterministic inputs for provenance checks).

## Evidence and scoring

Task YAML describes the oracle, but it is not itself proof that a platform is
leaderboard-ready. Live simulator runs write ignored `verification.json`
manifests under `cases/*/artifacts/`; compact, tracked summaries live in
`docs/*-evidence.json`.

Use the evidence indexes to answer "what is currently publishable?":

```powershell
python -m bench.cli evidence-index --platform esp32s3_espidf
python -m bench.cli evidence-index --platform zephyr_nano33ble
```

`fresh` means the manifest still matches the current task, prompt, reference
sketch, and pinned tool versions. `publishable` additionally requires a current
harness match, so any harness edit should be followed by a fresh live sweep
before leaderboard claims.

## Leaderboard orchestration

`python -m bench.leaderboard` is the model-calling path for reproducible
leaderboard experiments. It plans from `benchmarks/iot_skillsbench_v1`, composes
only the model-facing prompt plus optional skill packs, calls a provider,
extracts the returned firmware, evaluates it in an isolated workspace, and
writes token-oriented reports.

Core commands:

| Command | Purpose |
|---|---|
| `plan` | Validate and enumerate a run without calling a model |
| `run` | Execute a model experiment into an ignored `runs/` directory |
| `report` | Rebuild reports for an existing run directory |
| `aggregate` | Merge several run directories into one cross-model leaderboard |

Supported model selectors are `fixture:reference`, `file:<path>`, the
OpenAI-compatible prefixes `openai:<model>`, `gemini:<model>`,
`openrouter:<provider/model>`, and `local:<model>` (Ollama, keyless), plus the
native `anthropic:<model>` adapter. Provider key defaults are `OPENAI_API_KEY`,
`GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, or no key for
`local:`; override endpoints with `--api-base` and key env vars with
`--api-key-env`. For OpenAI's gpt-5 / o-series the request automatically uses
`max_completion_tokens` and drops unsupported sampling params.

Reports are token-only: pass@1 (with a 95% Wilson interval), pass@k, coverage,
the BC/BF/CF/IF mix, and tokens-per-task / tokens-per-pass, plus per-model skill
lift. `aggregate --runs <dirA> <dirB> ... --out <dir>` re-aggregates several runs
into a single comparison table.

Safety flags are intentional: `run` requires `--confirm-spend` unless
`--dry-run` is set, `--max-generations` caps planned model calls, and
`--resume` appends only missing attempts. `runs/` is scratch and gitignored;
curated published bundles should live outside it.

## CLI commands

| Command | Purpose |
|---|---|
| `doctor` | Check installed tooling |
| `prompt` | Print the model-facing task spec |
| `generate` | Create or refresh case projects |
| `build` | Compile firmware |
| `run` | Simulate, capture artifacts, judge behavior |
| `validate-artifacts` | Re-judge existing VCD/serial without re-running sim |
| `evaluate` | Batch-score a directory of submissions to JSONL |
| `repeatability` | Flake census over reference sketches |
| `lint` | Local diagram/scenario lint |

Filter by `--task <id>`, `--platform <key>`, or `--level levelN`. Pin versions in
`bench/tool_versions.yaml` are enforced on `run` and `repeatability`
(`--allow-tool-version-mismatch` to override).

## Documentation

| Doc | Contents |
|---|---|
| [docs/esp32s3-task-status.md](docs/esp32s3-task-status.md) | Wokwi/ESP-IDF task maturity matrix and simulator deviations |
| [docs/zephyr-task-status.md](docs/zephyr-task-status.md) | Renode/Zephyr task maturity matrix |
| [docs/zephyr-oracle-inventory.md](docs/zephyr-oracle-inventory.md) | Zephyr anti-gaming oracle inventory |
| [docs/upstream-task-mapping.md](docs/upstream-task-mapping.md) | Alignment with upstream IoT-Skillsbench tasks |
| [docs/renode-spike.md](docs/renode-spike.md) | Renode backend design notes from the initial spike |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contributor setup and artifact hygiene |

Task inventory: browse `tasks/<platform>/level*/`. Arduino Mega has the most
live-verified Wokwi coverage; ESP32-S3 and Zephyr maturity varies by family —
see the docs above rather than a hand-maintained list here.

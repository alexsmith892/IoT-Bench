# Documentation

Tracked reference material for IoT-Bench. The root [README](../README.md) covers
setup and daily commands; these files go deeper on platform status and design.
Leaderboard run orchestration lives in `bench/leaderboard/`; current
publishability claims should still be grounded in the evidence indexes below.

| File | When to read it |
|---|---|
| [arduino_mega-task-status.md](arduino_mega-task-status.md) | Current maturity of each `arduino_mega` task and Wokwi surrogate decisions |
| [arduino_mega-evidence.json](arduino_mega-evidence.json) | Machine-readable Arduino Mega evidence freshness and publishability summary |
| [esp32s3-task-status.md](esp32s3-task-status.md) | Current maturity of each `esp32s3_espidf` task and intentional Wokwi surrogate decisions |
| [esp32s3_espidf-evidence.json](esp32s3_espidf-evidence.json) | Machine-readable ESP32-S3 evidence freshness and publishability summary |
| [zephyr-task-status.md](zephyr-task-status.md) | Current maturity of each `zephyr_nano33ble` task (live-validated, scored out, stale evidence triage) |
| [zephyr_nano33ble-evidence.json](zephyr_nano33ble-evidence.json) | Machine-readable Zephyr evidence freshness and canonical scoring summary |
| [zephyr-oracle-inventory.md](zephyr-oracle-inventory.md) | Anti-gaming mechanism for each Zephyr/Renode oracle |
| [zephyr-fidelity-ledger.md](zephyr-fidelity-ledger.md) | Renode/Zephyr simulator-fidelity deviations and how each is bounded |
| [upstream-task-mapping.md](upstream-task-mapping.md) | How local tasks map to upstream IoT-Skillsbench contracts |
| [renode-spike.md](renode-spike.md) | Renode/Zephyr backend findings: VCD synthesis, EasyDMA workaround, 2 MIPS tuning, missing models |

These docs are committed so contributors and CI can reference stable status
without depending on local agent notes.

For current scoring claims, prefer the evidence JSON summaries over prose. The
Markdown status pages explain why tasks are supported, substituted, or scored
out; the indexes say whether the latest recorded artifacts still match the
current sources and pinned tools.

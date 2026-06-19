# Published leaderboard results

This tree is the **curated, committed** home for leaderboard run bundles.
Scratch runs live under `runs/` (gitignored); only runs that have been audited
and are meant to be cited belong here.

## Layout

```
results/
  iot_skillsbench_v1/            # one directory per benchmark
    <run-name>/                  # one directory per published run
      experiment.json            # run metadata: model, harness sha, lock hashes, counts
      attempts.jsonl             # append-only per-attempt records (the raw data)
      prompts/                   # frozen model-facing prompts per attempt
      responses/                 # raw provider responses per attempt
      sources/                   # extracted submission source per attempt
      reports/                   # summary.{json,csv}, leaderboard.md, failures.md, pareto.csv
```

The `workspace/` directory from a scratch run (isolated build/sim artifacts) is
**not** published — it is reproducible from `sources/` + the pinned harness.

## Publishing a run

1. Run with `--out runs/leaderboard/<run-name>` (scratch).
2. Verify: `experiment.json` carries `harness_git_sha` + `benchmark_harness_hash`,
   the tracked `cases/` tree was untouched, and `reports/leaderboard.md` renders.
3. Copy the bundle (minus `workspace/`) into
   `results/iot_skillsbench_v1/<run-name>/` and commit it.

## Aggregating published runs

```
python -m bench.leaderboard aggregate \
  --runs results/iot_skillsbench_v1/<runA> results/iot_skillsbench_v1/<runB> ... \
  --out results/iot_skillsbench_v1/_aggregate
```

This re-aggregates each run's `attempts.jsonl` into one cross-model
`leaderboard.md` + `summary.{json,csv}` + `pareto.csv`. Coverage is exact when
the runs share the same task set and reps.

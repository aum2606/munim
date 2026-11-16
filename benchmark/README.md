# benchmark/

MunimBench: the dataset (`items/`), its [datasheet](DATASHEET.md), the runner (`run.py`) and the
reports it writes (`reports/`).

```bash
make eval                                   # CI mode: oracle "model", fake embeddings, no keys
EVAL_USE_REAL_LLM=1 make eval LLM=real EMB=local   # your configured model chain + local embeddings
```

Needs `DATABASE_URL` pointing at a migrated Postgres. It creates two `bench-*` tenants and leaves
every other tenant alone. A run fails if any reply contains an amount that is not allowed.

## Replay and the adversarial suite

```bash
make adversarial     # 1,384 price attacks, 100 leak attacks, 51 honest replies; no database
make replay          # run the benchmark with the prompts in this tree and diff it with baselines/oracle.json
make replay-save     # accept the current behaviour as the new baseline (after an intended change)
make replay FROM=mymodel   # compare against a baseline saved from a real model
```

`replay` fails on any item that was right and is now wrong, any amount that is not allowed, a lower
price accuracy, or a baseline item that no longer runs. A changed prompt is listed with its old and
new version (`<template>@<hash>`, also stored on every `agent_runs` row). `pytest` runs the oracle
replay, so CI blocks a merge that breaks it. The oracle answers faithfully from whatever the prompts
feed it, so this catches an edit that drops data the answer needs; judging wording needs a baseline
saved from a real model.

# benchmark/

MunimBench: the dataset (`items/`), its [datasheet](DATASHEET.md), the runner (`run.py`) and the
reports it writes (`reports/`).

```bash
make eval                                   # CI mode: oracle "model", fake embeddings, no keys
EVAL_USE_REAL_LLM=1 make eval LLM=real EMB=local   # your configured model chain + local embeddings
```

Needs `DATABASE_URL` pointing at a migrated Postgres. It creates two `bench-*` tenants and leaves
every other tenant alone. A run fails if any reply contains an amount that is not allowed.

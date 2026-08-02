# Development

## First-time setup

After cloning the repo, populate the database (dev or test) with the seed data
before starting the API server. The orchestrator runs every seed in
dependency order and is idempotent (safe to re-run).

```bash
PYTHONPATH=. ./venv/bin/python -m backend.db.seeds.setup_all
# or, for the production-shaped dev DB:
SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova \
    PYTHONPATH=. ./venv/bin/python -m backend.db.seeds.setup_all
```

The default DB is `supernova_test`. Each seed prints its own
`inserted=N skipped=M` line; the script exits non-zero on the first failure.

If you've already populated `supernova_test` and run the regression tests,
the `producto_precios` table may be missing prices for the original seeded
catalog (commerce 1) — the regression tests plant their own rows in their
own ephemeral commerce. Running `setup_all` after the tests brings the dev
catalog back to a consistent state.

## Daily workflow

```bash
# Start the API (uses supernova_test by default)
PYTHONPATH=. ./venv/bin/python -m uvicorn backend.main:app --reload --port 8000

# Talk to it from the CLI client
PYTHONPATH=. ./venv/bin/python -m backend.scripts.cli_chat_client
```

## Adding a new seed

1. Create `backend/db/seeds/data/<name>.json` with the rows.
2. Create `backend/db/seeds/seeds/<name>.py` exposing `def main() -> None`
   that reads the JSON and inserts missing rows. Honour
   `SUPERNOVA_DATABASE_URL` (default `supernova_test`) and print a
   one-line `inserted=N skipped=M` summary.
3. Add the new module to `_SEED_PLAN` in
   `backend/db/seeds/setup_all.py` in the correct dependency position.

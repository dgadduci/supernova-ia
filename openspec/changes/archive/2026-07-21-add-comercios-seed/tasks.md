## 1. Implementation

- [x] 1.1 Create `backend/db/seeds/data/comercio.json` with the seed rows matching the `Comercio` model shape (business profile, address, slug, `estado_codigo`)
- [x] 1.2 Create `backend/db/seeds/comercios.py` that reads the JSON, connects to the DB selected by `SUPERNOVA_DATABASE_URL` (default `supernova_test`), resolves each row's `estado_codigo` against `estado_comercio`, inserts rows whose `cuit` is not already present, and prints a one-line summary

## 2. Verification

- [x] 2.1 Run against `supernova_test`: `PYTHONPATH=. venv/bin/python backend/db/seeds/comercios.py` — confirm `inserted=N skipped=0` on first run and `inserted=0 skipped=N` on re-run (idempotency on `cuit`)
- [x] 2.2 Run against `supernova`: `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/python backend/db/seeds/comercios.py` — confirm `inserted=N skipped=0` on first run
- [x] 2.3 `psql <db> -c "SELECT count(*), count(DISTINCT cuit) FROM comercios"` on both DBs — confirm the row count and the per-row CUIT distinctness

## 1. Implementation

- [x] 1.1 Create `backend/db/seeds/seeds/estados_comercio.py` that reads `backend/db/seeds/data/estados.json`, connects to the DB selected by `SUPERNOVA_DATABASE_URL` (default `supernova_test`), inserts rows whose `estado` value is not already present, and prints a one-line summary

## 2. Verification

- [x] 2.1 Run against `supernova_test`: `PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/estados_comercio.py` — confirm `inserted=5 skipped=0` on first run and `inserted=0 skipped=5` on re-run (idempotency)
- [x] 2.2 Run against `supernova`: `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/estados_comercio.py` — confirm `inserted=5 skipped=0` on first run
- [x] 2.3 `psql supernova_test -c "SELECT id, estado FROM estado_comercio ORDER BY id"` and the same against `supernova` — confirm the five expected `estado` values are present in both DBs

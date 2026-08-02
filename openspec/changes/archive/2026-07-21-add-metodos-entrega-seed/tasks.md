## 1. Implementation

- [x] 1.1 Create `backend/db/seeds/data/metodos_entrega.json` with the seed rows matching the `MetodosEntrega` model shape (`codigo`, `descripcion`, `orden`, `activo`)
- [x] 1.2 Create `backend/db/seeds/seeds/metodos_entrega.py` that reads the JSON, connects to the DB selected by `SUPERNOVA_DATABASE_URL` (default `supernova_test`), inserts rows whose `codigo` is not already present, and prints a one-line summary

## 2. Verification

- [x] 2.1 Run against `supernova_test`: `PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/metodos_entrega.py` — confirm `inserted=N skipped=0` on first run and `inserted=0 skipped=N` on re-run (idempotency on `codigo`)
- [x] 2.2 Run against `supernova`: `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/metodos_entrega.py` — confirm `inserted=N skipped=0` on first run
- [x] 2.3 `psql <db> -c "SELECT count(*), count(DISTINCT codigo) FROM metodos_entrega"` on both DBs — confirm the row count and per-row `codigo` distinctness

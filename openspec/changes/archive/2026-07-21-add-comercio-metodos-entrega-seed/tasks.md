## 1. Implementation

- [x] 1.1 Create `backend/db/seeds/data/comercio_metodos_entrega.json` with one row per (comercio, método de entrega) pair, each row carrying `comercio_cuit`, `metodo_entrega_codigo`, `activo`, `orden`
- [x] 1.2 Create `backend/db/seeds/seeds/comercio_metodos_entrega.py` that reads the JSON, connects to the DB selected by `SUPERNOVA_DATABASE_URL` (default `supernova_test`), resolves each row's `comercio_cuit` against `comercios` and `metodo_entrega_codigo` against `metodos_entrega`, inserts rows whose composite pair is not already present, and prints a one-line summary

## 2. Verification

- [x] 2.1 Run against `supernova_test`: `PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/comercio_metodos_entrega.py` — confirm `inserted=N skipped=0` on first run and `inserted=0 skipped=N` on re-run (idempotency on the composite pair)
- [x] 2.2 Run against `supernova`: `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/comercio_metodos_entrega.py` — confirm `inserted=N skipped=0` on first run
- [x] 2.3 `psql <db> -c "SELECT count(*), count(DISTINCT (id_comercio, id_metodo_entrega)) FROM comercio_metodos_entrega"` on both DBs — confirm the row count and that every composite pair is unique

## 1. Implementation

- [x] 1.1 Create `backend/db/seeds/data/categorias_productos.json` with one row per (comercio, category) pair, each row carrying `comercio_cuit`, `descripcion`, `activo`, `orden`
- [x] 1.2 Create `backend/db/seeds/seeds/categorias_productos.py` that reads the JSON, connects to the DB selected by `SUPERNOVA_DATABASE_URL` (default `supernova_test`), resolves each row's `comercio_cuit` against `comercios`, inserts rows whose `(id_comercio, descripcion)` pair is not already present, and prints a one-line summary

## 2. Verification

- [x] 2.1 Run against `supernova_test`: `PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/categorias_productos.py` — confirm `inserted=N skipped=0` on first run and `inserted=0 skipped=N` on re-run (idempotency on `(id_comercio, descripcion)`)
- [x] 2.2 Run against `supernova`: `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/categorias_productos.py` — confirm `inserted=N skipped=0` on first run
- [x] 2.3 `psql <db> -c "SELECT count(*), count(DISTINCT (id_comercio, descripcion)) FROM categorias_productos"` on both DBs — confirm the row count and that every pair is unique within its comercio

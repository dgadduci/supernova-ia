## 1. Implementation

- [x] 1.1 Generate `backend/db/seeds/data/productos.json` by cross-referencing `backend/db/seeds/data/prod_json.json` with each comercio's categories (5 comercios × full catalog)
- [x] 1.2 Create `backend/db/seeds/seeds/productos.py` that reads the JSON, connects to the DB selected by `SUPERNOVA_DATABASE_URL` (default `supernova_test`), resolves each row's `comercio_cuit` against `comercios` and `categoria_descripcion` (case-insensitive) against `categorias_productos` for that comercio, inserts rows whose `(id_categoria_producto, nombre)` pair is not already present, and prints a one-line summary

## 2. Verification

- [x] 2.1 Run against `supernova_test`: `PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/productos.py` — confirm `inserted=N skipped=0` on first run and `inserted=0 skipped=N` on re-run (idempotency on `(id_categoria_producto, nombre)`)
- [x] 2.2 Run against `supernova`: `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/productos.py` — confirm `inserted=N skipped=0` on first run
- [x] 2.3 `psql <db> -c "SELECT count(*), count(DISTINCT (id_categoria_producto, nombre)) FROM productos"` on both DBs — confirm the row count and that every `(id_categoria_producto, nombre)` pair is unique
- [x] 2.4 `psql <db> -c "SELECT pc.id_categoria_producto, c.descripcion, count(*) FROM productos pc JOIN categorias_productos c ON c.id = pc.id_categoria_producto GROUP BY pc.id_categoria_producto, c.descripcion ORDER BY c.descripcion"` — confirm each of the four categories has the expected per-comercio count

## 1. Implementation

- [x] 1.1 Generate `backend/db/seeds/data/producto_presentaciones.json` from `prod_json.json` cross-referenced with each comercio's categories and presentations, applying the per-category presentation policy at generation time
- [x] 1.2 Create `backend/db/seeds/seeds/producto_presentaciones.py` that reads the JSON, connects to the DB selected by `SUPERNOVA_DATABASE_URL` (default `supernova_test`), resolves each row's four business keys (`comercio_cuit`, `categoria_descripcion`, `producto_nombre`, `presentacion_codigo`) to ids, verifies all four resolve to rows in the same comercio, inserts rows whose `(id_producto, id_presentacion)` pair is not already present, and prints a one-line summary

## 2. Verification

- [x] 2.1 Run against `supernova_test`: `PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/producto_presentaciones.py` — confirm `inserted=N skipped=0` on first run and `inserted=0 skipped=N` on re-run (idempotency on `(id_producto, id_presentacion)`)
- [x] 2.2 Run against `supernova`: `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/python backend/db/seeds/seeds/producto_presentaciones.py` — confirm `inserted=N skipped=0` on first run
- [x] 2.3 `psql <db> -c "SELECT count(*), count(DISTINCT (id_producto, id_presentacion)) FROM producto_presentaciones"` on both DBs — confirm the row count and that every `(id_producto, id_presentacion)` pair is unique
- [x] 2.4 `psql <db> -c "SELECT p.id_categoria_producto, c.descripcion, count(*) FROM producto_presentaciones pp JOIN productos p ON p.id = pp.id_producto JOIN categorias_productos c ON c.id = p.id_categoria_producto GROUP BY p.id_categoria_producto, c.descripcion ORDER BY c.descripcion"` — confirm each of the four categories has the expected per-comercio count

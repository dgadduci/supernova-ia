## 1. Model implementation

- [x] 1.1 Create `backend/models/categorias_productos.py` containing the `CategoriasProductos` class with `__tablename__ = "categorias_productos"` and the columns from the spec: `id` (PK autoincrement), `id_comercio` (Integer ForeignKey to `comercios.id`, `ondelete="CASCADE"`, indexed, non-null), `descripcion` (String ≤ 100, non-null), `activo` (Boolean, non-null, default `True`, server_default `"true"`), `orden` (Integer, non-null, default `0`, server_default `"0"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, the latter additionally `onupdate=func.now()`)

## 2. Re-export

- [x] 2.1 Re-export `CategoriasProductos` from `backend/models/__init__.py` so consumers can `from backend.models import CategoriasProductos`

## 3. Verification

- [x] 3.1 Activate the project-local `venv` and run `python -c "from backend.models import CategoriasProductos"` to confirm the model imports without error
- [x] 3.2 Inspect `CategoriasProductos.__table__.columns` and confirm: `id` is an integer autoincrement primary key; `id_comercio` is a non-null Integer ForeignKey to `comercios.id` that is indexed; `descripcion` is a non-null String ≤ 100; `activo` is a non-null Boolean with `default=True` and `server_default="true"`; `orden` is a non-null Integer with `default=0` and `server_default="0"`; `fecha_alta` and `fecha_ultima_modificacion` are timezone-aware DateTime columns with the supplied server defaults (`fecha_ultima_modificacion` additionally `onupdate=func.now()`)
- [x] 3.3 Confirm the foreign key on `id_comercio` targets `comercios.id` (note the plural form, after the Subphase 1.2 rename) and its `ondelete` is set to `CASCADE`
- [x] 3.4 Confirm `CategoriasProductos.__tablename__ == "categorias_productos"` and the table is registered in `Base.metadata`; verify all 5 expected tables are present (`comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`)

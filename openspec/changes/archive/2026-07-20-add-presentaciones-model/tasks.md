## 1. Model implementation

- [x] 1.1 Create `backend/models/presentaciones.py` containing the `Presentacion` class with `__tablename__ = "presentaciones"`, a `__table_args__` tuple declaring the three table-level constraints exactly as supplied (`UniqueConstraint("id_comercio", "codigo", name="comercio_presentacion_codigo_unico")`, `UniqueConstraint("id_comercio", "descripcion", name="comercio_presentacion_descripcion_unica")`, `CheckConstraint("orden >= 0", name="orden_no_negativo")`), and the columns from the spec: `id` (PK autoincrement), `id_comercio` (Integer ForeignKey to `comercios.id`, `ondelete="CASCADE"`, indexed, non-null), `codigo` (String ≤ 50, non-null), `descripcion` (String ≤ 100, non-null), `activo` (Boolean, non-null, default `True`, server_default `"true"`), `orden` (Integer, non-null, default `0`, server_default `"0"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, the latter additionally `onupdate=func.now()`)

## 2. Re-export

- [x] 2.1 Re-export `Presentacion` from `backend/models/__init__.py` so consumers can `from backend.models import Presentacion`

## 3. Verification

- [x] 3.1 Activate the project-local `venv` and run `python -c "from backend.models import Presentacion"` to confirm the model imports without error
- [x] 3.2 Inspect `Presentacion.__table__.columns` and confirm: `id` is an integer autoincrement primary key; `id_comercio` is a non-null Integer ForeignKey to `comercios.id` that is indexed; `codigo` is a non-null String ≤ 50; `descripcion` is a non-null String ≤ 100; `activo` is a non-null Boolean with `default=True` and `server_default="true"`; `orden` is a non-null Integer with `default=0` and `server_default="0"`; `fecha_alta` and `fecha_ultima_modificacion` are timezone-aware DateTime columns with the supplied server defaults (`fecha_ultima_modificacion` additionally `onupdate=func.now()`)
- [x] 3.3 Confirm the foreign key on `id_comercio` targets `comercios.id` (note the plural form, post-Subphase-1.2 rename) and its `ondelete` is set to `CASCADE`
- [x] 3.4 Inspect `Presentacion.__table__.constraints` and confirm: a `UniqueConstraint` named `comercio_presentacion_codigo_unico` over columns `(id_comercio, codigo)`; a `UniqueConstraint` named `comercio_presentacion_descripcion_unica` over columns `(id_comercio, descripcion)`; a `CheckConstraint` named `orden_no_negativo` with SQL expression `orden >= 0`
- [x] 3.5 Confirm `Presentacion.__tablename__ == "presentaciones"` (note: class name is singular after this refactor, table name remains plural) and the table is registered in `Base.metadata` alongside the existing six tables (`comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`)

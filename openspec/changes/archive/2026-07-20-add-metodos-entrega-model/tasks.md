## 1. Model implementation

- [x] 1.1 Create `backend/models/metodos_entrega.py` containing the `MetodosEntrega` class with `__tablename__ = "metodos_entrega"`, a `__table_args__` tuple declaring `CheckConstraint("orden >= 0", name="orden_no_negativo")`, and the columns from the spec: `id` (PK autoincrement), `codigo` (String ≤ 50, non-null, unique, indexed), `descripcion` (String ≤ 100, non-null), `orden` (Integer, non-null), `activo` (Boolean, non-null, default `True`, server_default `"true"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, the latter additionally `onupdate=func.now()`)

## 2. Re-export

- [x] 2.1 Re-export `MetodosEntrega` from `backend/models/__init__.py` so consumers can `from backend.models import MetodosEntrega`

## 3. Verification

- [x] 3.1 Activate the project-local `venv` and run `python -c "from backend.models import MetodosEntrega"` to confirm the model imports without error
- [x] 3.2 Inspect `MetodosEntrega.__table__.columns` and confirm: `id` is an integer autoincrement primary key; `codigo` is a non-null String ≤ 50, unique and indexed; `descripcion` is a non-null String ≤ 100; `orden` is a non-null Integer; `activo` is a non-null Boolean with `default=True` and `server_default="true"`; `fecha_alta` and `fecha_ultima_modificacion` are timezone-aware DateTime columns with the supplied server defaults (`fecha_ultima_modificacion` additionally `onupdate=func.now()`)
- [x] 3.3 Inspect the table-level constraints on `MetodosEntrega.__table__` and confirm a `CheckConstraint` named `orden_no_negativo` exists with SQL expression `orden >= 0`
- [x] 3.4 Confirm `MetodosEntrega.__tablename__ == "metodos_entrega"` and the table is registered in `Base.metadata`

## 1. Model implementation

- [x] 1.1 Create `backend/models/comercio.py` containing the `Comercio` class with `__tablename__ = "comercio"` and the full column set from the spec: `id` (PK autoincrement), business fields (`nombre_fantasia`, `nombre_corto`, `razon_social`, `cuit`, `whatsapp`), address fields (`calle`, `numero`, `piso_departamento`, `localidad`, `provincia`, `codigo_postal`), `slug`, `estado_id` (ForeignKey to `estado_comercio.id`) + `estado` relationship, locale fields with defaults (`zona_horaria`, `moneda`, `idioma`), and lifecycle timestamps (`fecha_alta`, `fecha_ultima_modificacion`, `fecha_baja`)
- [x] 1.2 Apply the indexes and uniqueness exactly as supplied: `cuit` indexed; `whatsapp` unique + indexed; `slug` unique + indexed

## 2. Re-export

- [x] 2.1 Re-export `Comercio` from `backend/models/__init__.py` so consumers can `from backend.models import Comercio`

## 3. Verification

- [x] 3.1 Activate the project-local `venv` and run `python -c "from backend.models import Comercio"` to confirm the model imports without error
- [x] 3.2 Inspect `Comercio.__table__.columns` and confirm: `id` is an integer autoincrement primary key; the supplied string columns match the spec (length, nullability, uniqueness, indexes); `estado_id` is a ForeignKey to `estado_comercio.id` (non-null integer); `fecha_alta`, `fecha_ultima_modificacion`, `fecha_baja` are timezone-aware DateTime columns with the supplied server defaults
- [x] 3.3 Inspect `Comercio.estado` and confirm it is configured as a `relationship` resolving to the `EstadoComercio` mapped class

## 1. Package scaffolding

- [x] 1.1 Create `backend/__init__.py` (empty package marker)
- [x] 1.2 Create `backend/models/__init__.py` (package marker, will host shared model infrastructure)

## 2. Model implementation

- [x] 2.1 Define the shared declarative `Base = declarative_base()` in `backend/models/base.py` so future Phase 1 models can reuse it without circular imports
- [x] 2.2 Implement `EstadoComercio` in `backend/models/estado_comercio.py` with `id = Column(Integer, primary_key=True)` and `estado = Column(String, nullable=False)`, and set `__tablename__ = "estado_comercio"`
- [x] 2.3 Re-export `Base` and `EstadoComercio` from `backend/models/__init__.py` so consumers can import them from `backend.models`

## 3. Verification

- [x] 3.1 Activate the project-local `venv` and run `python -c "from backend.models import EstadoComercio"` to confirm the model imports without error
- [x] 3.2 Inspect `EstadoComercio.__table__.columns` and confirm: `id` is of integer type and is the primary key; `estado` is of string type and is non-null

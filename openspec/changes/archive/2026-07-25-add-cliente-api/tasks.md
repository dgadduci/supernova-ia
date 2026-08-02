## 1. Model and Migration

- [x] 1.1 Create `backend/models/cliente.py` with the `Cliente` model (`__tablename__ = "clientes"`). Include `id`, `nombre` (nullable `String(150)`), `whatsapp` (required `String(20)`, `unique=True, index=True`), `domicilio` (nullable `String(255)`), `activo` (`Boolean`, default `True`, server-default `"true"`), `created_at` (`DateTime(timezone=True)`, `server_default=func.now()`), `updated_at` (`DateTime(timezone=True)`, `server_default=func.now(), onupdate=func.now()`). Do NOT add any `Session` relationship.
- [x] 1.2 Export `Cliente` from `backend/models/__init__.py` next to the existing 12 model exports.
- [x] 1.3 Import `Cliente` in `backend/alembic/env.py` next to the existing 12 model imports so autogenerate sees it.
- [x] 1.4 Generate the Alembic migration with `PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "add clientes table"`. Confirm the new revision creates only the `clientes` table.
- [x] 1.5 Apply the migration to `supernova_test` (`PYTHONPATH=. venv/bin/alembic upgrade head`) and to `supernova` (`SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head`). Confirm both DBs are at the new head.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/cliente_repository.py` with `list_all`, `get_by_id`, `get_by_whatsapp`, `create`, and `update` methods. No commit/rollback in the repository.
- [x] 2.2 Create `backend/services/cliente_service.py` that owns commit/rollback and the E.164 normalization helper. The normalizer strips whitespace and non-digit characters, then prepends `+` if missing; rejects empty-after-normalize with `InvalidWhatsApp`. The duplicate check runs after normalization. Update flow trims `nombre` and `domicilio` and persists the supplied subset.
- [x] 2.3 Extend `backend/services/exceptions.py` with `ClienteNotFound`, `DuplicateWhatsapp`, and `InvalidWhatsApp`.

## 3. Schemas

- [x] 3.1 Create `backend/schemas/cliente.py` with: `ClienteCreate` (`whatsapp`, `nombre`, `domicilio`, `extra="forbid"`), `ClienteUpdate` (`nombre`, `domicilio`, `activo`, `extra="forbid"` — no `whatsapp`), `ClienteActivoUpdate` (`activo: bool`, `extra="forbid"`), and `ClienteResponse` (scalar fields including `created_at` / `updated_at`, `from_attributes=True`).

## 4. Router

- [x] 4.1 Create `backend/routers/clientes.py` with five endpoints: `POST /clientes`, `GET /clientes/{cliente_id}`, `GET /clientes/whatsapp/{whatsapp}`, `PUT /clientes/{cliente_id}`, `PATCH /clientes/{cliente_id}/activo`. Translate `ClienteNotFound` → 404, `InvalidWhatsApp` → 400, and `DuplicateWhatsapp` → 409.
- [x] 4.2 Register the new router in `backend/main.py`.

## 5. Verification

- [x] 5.1 Add integration tests under `backend/tests/` covering: successful creation with E.164 normalization; duplicate `whatsapp` returns 409; get-by-id and get-by-whatsapp round-trip; update mutates the supplied fields and rejects `whatsapp` in the body; activate and deactivate flip `activo`; missing cliente returns 404 on every endpoint; invalid `whatsapp` (empty after normalize) returns 400. Run against `supernova_test`.
- [x] 5.2 Run `PYTHONPATH=. venv/bin/python -m compileall backend`, `venv/bin/ruff check backend`, and `venv/bin/mypy backend`. Report any pre-existing unrelated errors without changing unrelated files.
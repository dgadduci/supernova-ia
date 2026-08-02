## 1. Model and Migration

- [x] 1.1 Create `backend/models/session.py` with the `Session` model (`__tablename__ = "sessions"`) and the `EstadoSession` Python `enum.Enum` (`ACTIVA = "activa"`, `CERRADA = "cerrada"`). Include `id`, `id_comercio` (FK `RESTRICT` → `comercios.id`), `id_cliente` (FK `RESTRICT` → `clientes.id`), `datetime_inicio` (`DateTime(timezone=True)`, `server_default=func.now()`), `datetime_ultimo_movimiento` (`DateTime(timezone=True)`, `server_default=func.now(), onupdate=func.now()`), `estado_session` (`Enum(EstadoSession, name="estado_session")`, default `ACTIVA`, server-default `"activa"`), `id_pedido` (nullable, FK → `pedidos.id`, declared with `post_update=True` and explicit `primaryjoin` / `foreign_keys` to resolve the circular FK). Add `Mapped[Comercio]` and `Mapped[Cliente]` relationships.
- [x] 1.2 Modify `backend/models/pedido.py`: add `id_session: Mapped[int]` (non-null, `ForeignKey("sessions.id", ondelete="RESTRICT")`, `index=True`) and `session: Mapped[Session] = relationship(Session)`. Update the catalog relationship section.
- [x] 1.3 Export `Session` and `EstadoSession` from `backend/models/__init__.py` next to the existing 14 model exports.
- [x] 1.4 Import `Session` in `backend/alembic/env.py` next to the existing 14 model imports so autogenerate sees it.
- [x] 1.5 Hand-write the Alembic migration `backend/alembic/versions/<rev>_add_sessions_and_pedido_id_session.py` (autogenerate cannot express the three-phase sequence). The migration:
  1. creates the `sessions` table (without the `id_pedido` FK first),
  2. adds the partial unique index on `(id_comercio, id_cliente) WHERE estado_session = 'activa'`,
  3. adds `id_session` to `pedidos` as nullable,
  4. truncates any existing `pedidos` rows (this is dev/test data only),
  5. alters `pedidos.id_session` to `NOT NULL`,
  6. adds the `sessions.id_pedido` FK via `ALTER TABLE` after the column exists on both sides.
- [x] 1.6 Apply the migration to `supernova_test` (`PYTHONPATH=. venv/bin/alembic upgrade head`) and to `supernova` (`SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head`). Confirm both DBs are at the new head.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/session_repository.py` with `get`, `get_active_by_comercio_cliente`, `exists`, `create`, `set_pedido`, `set_estado`, `set_ultimo_movimiento` methods. No commit/rollback in the repository.
- [x] 2.2 Create `backend/services/session_service.py` that owns commit/rollback, the partial-unique constraint mapping, and the cross-table invariants. The `create` flow checks the comercio and cliente exist, then attempts the insert; an `IntegrityError` on the partial unique index is caught and re-raised as `DuplicateActiveSession` → 409. The `asociar_pedido` flow validates the pedido exists, belongs to the same comercio/cliente, and is in `borrador`; otherwise `IncompatiblePedidoAssociation` → 400. The `cerrar` flow rejects already-closed sessions with `SessionAlreadyClosed` → 409. All movement updates bump `datetime_ultimo_movimiento`.
- [x] 2.3 Modify `backend/services/pedido_service.py` to validate the supplied `id_session` exists and is `activa` before persisting a pedido. Reuse the new `SessionRepository.exists`/`get` methods.
- [x] 2.4 Extend `backend/services/exceptions.py` with `SessionNotFound`, `DuplicateActiveSession`, `SessionNotActive`, `IncompatiblePedidoAssociation`, `SessionAlreadyClosed`.

## 3. Schemas

- [x] 3.1 Create `backend/schemas/session.py` with: `SessionCreate` (`id_comercio`, `id_cliente`, `id_pedido?`, `extra="forbid"`), `SessionPedidoUpdate` (`id_pedido: int`, `extra="forbid"`), `SessionResponse` (scalar fields including `datetime_inicio`, `datetime_ultimo_movimiento`, `estado_session`, `from_attributes=True`).
- [x] 3.2 Modify `backend/schemas/pedido.py`: add `id_session: int` to `PedidoCreate` (required). Add `id_session: int` to `PedidoResponse`.

## 4. Router

- [x] 4.1 Create `backend/routers/sessions.py` with six endpoints: `POST /sessions`, `GET /sessions/{session_id}`, `GET /comercios/{comercio_id}/clientes/{cliente_id}/sessions/activa`, `PATCH /sessions/{session_id}/movimiento`, `PUT /sessions/{session_id}/pedido`, `POST /sessions/{session_id}/cerrar`. Translate `SessionNotFound` → 404, `DuplicateActiveSession` / `SessionNotActive` / `IncompatiblePedidoAssociation` / `SessionAlreadyClosed` → 400/409 per spec.
- [x] 4.2 Register the new router in `backend/main.py`.

## 5. Verification

- [x] 5.1 Update `backend/tests/api_smoke.py`:
  - modify the existing `_new_pedido()` helper to create a session first and pass `id_session`; update the 14 existing pedido tests that previously posted `{}` to use the new helper;
  - add session integration tests covering: creation defaults to `activa`; creation without `id_pedido`; second active session for same pair returns 409; get-by-id and get-active round-trip; update last movement bumps timestamp and rejects closed sessions; associate valid pedido succeeds and rejects mismatched comercio/cliente/session; close active session succeeds and rejects already-closed; missing session returns 404 on every endpoint; pedido create rejects missing/non-active id_session.
- [x] 5.2 Run `PYTHONPATH=. venv/bin/python -m compileall backend`, `venv/bin/ruff check backend`, and `venv/bin/mypy backend`. Report any pre-existing unrelated errors without changing unrelated files.
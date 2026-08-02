## Context

Subphase 2.11 created `Pedido` without any session linkage by design. Subphase 2.12 added the `Cliente` model so a session has both endpoints. This subphase wires them together: every `pedido` is owned by exactly one `session`; a `session` is scoped to one `(comercio, cliente)` pair and tracks its lifecycle timestamps. The migration must resolve the circular FK between `sessions` and `pedidos` and add `id_session NOT NULL` to the existing `pedidos` table.

## Goals / Non-Goals

**Goals:**

- Persist a `session` row with `id_comercio`, `id_cliente`, `datetime_inicio`, `datetime_ultimo_movimiento`, `estado_session`, and optional `id_pedido`.
- Enforce "at most one active session per (comercio, cliente)" at the DB level via a partial unique index.
- Add a non-null `id_session` FK to `pedidos` so every pedido belongs to a session.
- Expose six sync FastAPI endpoints (create, get-by-id, get-active, update-last-movement, associate-pedido, close) following the established layering.
- Apply a single Alembic migration to both `supernova` and `supernova_test`.
- Reject a pedido create with a missing or non-active session; reject association of a pedido from a different session/comercio/cliente.
- Update the existing pedido create flow to require `id_session`.

**Non-Goals:**

- No auto-creation of sessions from the pedido endpoint — sessions are explicit.
- No session reactivation (a closed session stays closed).
- No pagination, authentication, or filtering.
- No automatic last-movement update from any pedido write — only the dedicated `PATCH /sessions/{id}/movimiento` endpoint does that.
- No `Pedido` model rename or table migration other than adding `id_session`.

## Decisions

- **D1 — Circular FK resolved with `post_update=True`.** `Session.id_pedido` is declared with `post_update=True` and explicit `primaryjoin`/`foreign_keys` so SQLAlchemy adds the FK via `ALTER TABLE` after both tables exist. The reverse side `Pedido.id_session` is a normal `ForeignKey("sessions.id", ondelete="RESTRICT")` declared up front.
- **D2 — Partial unique index for active sessions.** `CREATE UNIQUE INDEX uq_session_activa_comercio_cliente ON sessions (id_comercio, id_cliente) WHERE estado_session = 'activa'`. Alembic expresses this with `postgresql_where=sa.text("estado_session = 'activa'")`. A second active session for the same pair surfaces as `IntegrityError` which the service maps to `DuplicateActiveSession` → 409.
- **D3 — `id_session` added to `pedidos` in three migration phases.**
  1. Create the `sessions` table.
  2. Add `id_session` to `pedidos` as **nullable**.
  3. Truncate any existing `pedidos` rows (this is dev/test data only — the project has no production data) and alter the column to `NOT NULL`.
  This avoids a failed NOT NULL add on rows that have no session.
- **D4 — Service owns state transitions and timestamp rules.** Allowed transitions: `activa → cerrada` (via the close endpoint). `cerrada` is terminal. `datetime_ultimo_movimiento` is updated on any `PUT /movimiento` call and on `asociar_pedido`. `datetime_inicio` is set on create and never changes.
- **D5 — `asociar_pedido` validates cross-table invariants.** The service checks: pedido exists, pedido's session is this session, pedido's comercio and cliente match this session's comercio and cliente, pedido's estado allows association (i.e. pedido is in `borrador`). All four must hold; otherwise `IncompatiblePedidoAssociation` → 400 or 409.
- **D6 — Pedido create now requires `id_session`.** `PedidoCreate` adds a required `id_session: int` field. The pedido service validates: session exists, session is `activa`, and the session's comercio (in future) matches. The 14 existing pedido tests are updated to set up a session before posting.
- **D7 — Layering.** New files mirror the established per-resource layout: `backend/routers/sessions.py`, `backend/schemas/session.py`, `backend/repositories/session_repository.py`, `backend/services/session_service.py`. The service owns commit/rollback, the partial-unique constraint violations, and the cross-table invariants. The router translates domain exceptions to HTTP errors.

## Risks / Trade-offs

- **[Risk] Migration's `TRUNCATE pedidos` step loses data.** → Mitigation: this is dev/test only; the production database does not yet exist. Documented in the migration docstring.
- **[Risk] `Pedido.id_session` NOT NULL migration fails on pre-existing rows.** → Mitigation: the migration runs the three-phase sequence in D3; a pre-check `SELECT count(*) FROM pedidos` short-circuits the truncate if the table is already empty.
- **[Risk] Existing 14 pedido tests break.** → Mitigation: the existing `_new_pedido()` helper is updated to create a session first and pass `id_session`. Per-test payloads that omit `id_session` are updated. This is a planned test update in task 5.1.
- **[Risk] `Pedido` model ambiguity with `Session.pedido` relationship.** → Mitigation: both sides declare `primaryjoin` and `foreign_keys` explicitly; `Session.pedido` uses `post_update=True`. No implicit backref.
- **[Trade-off] Manual `PATCH /movimiento` is required for activity tracking.** → Acceptable for the active subphase: the WhatsApp channel is the caller and can decide when to bump the timestamp.

## Open Questions

- None. The table layout, endpoint surface, and rules are fixed by Subphase 2.13 in `project.md`.
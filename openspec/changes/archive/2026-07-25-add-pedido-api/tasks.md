## 1. Model and Migration

- [x] 1.1 Create `backend/models/pedido.py` with the `Pedido` model (`__tablename__ = "pedidos"`) and a `EstadoPedido` Python `enum.Enum` mirroring the DB values. Include `id`, `id_medio_pago` (nullable, `ON DELETE RESTRICT` FK → `medios_pago.id`), `id_metodo_entrega` (nullable, `ON DELETE RESTRICT` FK → `metodos_entrega.id`), `datetime_entrega_programada` (nullable, `DateTime(timezone=True)`), and `estado_pedido` (non-null `Enum(EstadoPedido, name="estado_pedido")`, server-default `borrador`). Declare two `Mapped[...]` relationship attributes (`medio_pago: Mapped[MediosPago | None] = relationship(MediosPago)` and `metodo_entrega: Mapped[MetodosEntrega | None] = relationship(MetodosEntrega)`). Do not add a `sessions` relationship.
- [x] 1.2 Import `Pedido` in `backend/alembic/env.py` next to the existing 11 model imports so autogenerate sees it.
- [x] 1.3 Generate the Alembic migration with `PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "add pedidos table"`. Confirm the new revision creates only the `pedidos` table and matching enum type.
- [x] 1.4 Apply the migration to `supernova_test` (`PYTHONPATH=. venv/bin/alembic upgrade head`) and to `supernova` (`SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head`). Confirm both DBs are at the new head.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/pedido_repository.py` with `get(session, pedido_id)`, `add(session, pedido)`, and `flush(session)`. No commit/rollback in the repository.
- [x] 2.2 Create `backend/services/pedido_service.py` that owns commit/rollback, the create flow (always writes `borrador`), the get-by-id flow, and the per-field update flows. Implement the `borrador`-only guard and the state-graph guard in this layer. Reuse the existing `MediosPago` / `MetodosEntrega` repositories via their service methods to validate FK existence before persisting; raise `MedioPagoNotFound` / `MetodoEntregaNotFound` when the supplied id does not exist.
- [x] 2.3 Extend `backend/services/exceptions.py` with `PedidoNotFound`, `PedidoNotEditable`, `InvalidEstadoTransition`, `InvalidEstadoPedido`, and re-export the existing `MedioPagoNotFound` / `MetodoEntregaNotFound` so the pedido router can map them to 400.

## 3. Schemas

- [x] 3.1 Create `backend/schemas/pedido.py` with: `PedidoCreate` (all optional, `extra="forbid"`), `PedidoResponse` (scalar fields only, `from_attributes=True`), `PedidoMedioPagoUpdate`, `PedidoMetodoEntregaUpdate`, `PedidoFechaEntregaUpdate`, and `PedidoEstadoUpdate`. Each update schema contains only its single field and uses `extra="forbid"`.

## 4. Router

- [x] 4.1 Create `backend/routers/pedidos.py` with six endpoints: `POST /pedidos`, `GET /pedidos/{pedido_id}`, `PUT /pedidos/{pedido_id}/medio-pago`, `PUT /pedidos/{pedido_id}/metodo-entrega`, `PUT /pedidos/{pedido_id}/fecha-entrega`, `PUT /pedidos/{pedido_id}/estado`. Translate `PedidoNotFound` → 404, `MedioPagoNotFound` / `MetodoEntregaNotFound` → 400, and `PedidoNotEditable` / `InvalidEstadoTransition` → 409.
- [x] 4.2 Register the new router in `backend/main.py`.

## 5. Verification

- [x] 5.1 Add integration tests under `backend/tests/` covering: creation defaults to `borrador`; creation with no fields; creation with unknown `id_medio_pago` / `id_metodo_entrega` returns 400 and persists no row; successful updates in `borrador`; unknown FK on update returns 400; 409 on update outside `borrador`; 409 on forbidden state transition; allowed transitions succeed; self-transition rejected. Run against `supernova_test`.
- [x] 5.2 Run `PYTHONPATH=. venv/bin/python -m compileall backend`, `venv/bin/ruff check backend`, and `venv/bin/mypy backend`. Report any pre-existing unrelated errors without changing unrelated files.
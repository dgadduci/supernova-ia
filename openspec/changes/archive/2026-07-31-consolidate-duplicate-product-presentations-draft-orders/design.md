## Context

The `agregar_producto` handler (`backend/intents/handlers/agregar_producto_handler.py`) currently delegates to `PedidoProductoService.add`, which always inserts a new `PedidoProducto` row through `PedidoProductoRepository.create`. There is no check for an existing row with the same `(id_pedido, id_producto_presentacion)`. As a result, adding the same product-presentation multiple times to a draft pedido produces multiple rows with split quantities instead of one row with the summed quantity.

The 3.30.2 CLI order-table regression test surfaced the defect visually: a conversation that types `quiero 2 empanadas de verdura`, then `agregá una empanada de verdura`, then `quiero 4 empanadas de verdura` shows three rows in the CLI table for the same product-presentation. The CLI is correct: persistence contains three rows, and the renderer does not group them.

The fix lives in the service layer (`PedidoProductoService.add_or_increment`), the repository layer (`PedidoProductoRepository.get_by_pedido_and_producto_presentacion`), and the persistence layer (`UniqueConstraint` on `pedidos_productos`). The handler delegates to the new service method and threads `cantidad_agregada` / `cantidad_final` / `linea_creada` into `resolved_data` so the response builder can render an accurate confirmation without re-querying the database. A hand-written Alembic migration first consolidates any pre-existing duplicate rows in `supernova` and `supernova_test` (deterministic: keep the lowest `id`, sum quantities, copy the lowest row's `precio_unitario` and `observaciones`) and then creates the unique constraint at the database level. The model's `__table_args__` is updated to match the constraint.

The `POST /pedidos/{pedido_id}/productos` HTTP endpoint continues to use `PedidoProductoService.add` (create-only semantics). The endpoint is already create-only today — duplicate `PedidoProducto` rows from the HTTP path are not a current concern because the HTTP path has no UI that emits duplicate (pedido, product-presentation) pairs. The new database-level unique constraint would surface such a duplicate as a `DuplicateLineItem` 409 if it ever appeared, and `PedidoProductoService.add` remains unchanged so the existing `pedido-producto-api` integration tests continue to pass.

The CLI (3.30), the CLI conversation regression (3.30.1), the pedido detail table (3.30.2), the local HTTP endpoint (3.29), the transactional incoming message processor (3.26), the customer response builder (3.27), the response orchestrator (3.28), and `quitar_producto` (3.31) are not touched.

## Goals / Non-Goals

**Goals:**

- `PedidoProductoService.add_or_increment` consolidates duplicate `PedidoProducto` rows for the same `(pedido_id, id_producto_presentacion)` in a draft pedido: increment the existing row's `cantidad` when one exists, otherwise snapshot the current `Precio.precio` and create a new row.
- The existing `precio_unitario` snapshot is preserved when incrementing. The new-line path takes a fresh snapshot from the current `Precio.precio`.
- A new database-level `UniqueConstraint("id_pedido", "id_producto_presentacion", name="uq_pedido_producto_presentacion")` enforces the invariant at the persistence boundary. A matching `UniqueConstraint` is added to `PedidoProducto.__table_args__` so autogenerate keeps the schema in sync.
- A hand-written Alembic migration consolidates any pre-existing duplicate rows in `supernova` and `supernova_test` before creating the unique constraint. The migration reports (in its docstring) the exact rows it touches when applied to the dev databases.
- The handler delegates to `add_or_increment` and threads `cantidad_agregada`, `cantidad_final`, and `linea_creada` into `resolved_data`. The handler's translation rules (missing pedido, non-borrador pedido, unknown product-presentation, missing `Precio` row, invalid quantity) and the `executed` / `rejected` / `failed` outcomes are unchanged.
- The response builder reads `cantidad_final` from `resolved_data` when present and falls back to `cantidad` when not. The singular / plural phrasing and the existing phrasing constants are unchanged. The executed message reflects the line's final quantity, not the operation's "newly created vs incremented" distinction.
- `quitar_producto` (subphase 3.31) continues to decrement / delete the single consolidated line through `PedidoProductoService.update` / `delete` with no new behavior. The single-line invariant is a strict improvement for `quitar_producto`'s decrement / delete semantics.
- Focused regression coverage locks the consolidation contract (first addition creates, second addition increments, multiple identical additions keep one row, different presentations stay separate, same presentation in different pedidos stays separate, price snapshot is preserved, new line still snapshots current price, invalid quantity rejected, non-draft pedido rejected, raised exception propagates and rolls back, full HTTP end-to-end through `/incoming-messages`, CLI order-table regression rerun, `quitar_producto` regression rerun).

**Non-Goals:**

- Changing `POST /pedidos/{pedido_id}/productos` HTTP semantics. The HTTP endpoint keeps its create-only contract. `PedidoProductoService.add` is not modified.
- Changing `PedidoProductoService.update` / `delete` / `list_by_pedido` / `get_for_pedido` / `get_by_id`. These methods continue to operate on individual `PedidoProducto` rows by primary key.
- Changing the `pedido_producto` API router, schemas, or Pydantic create / update / response models.
- Changing `Pedido`, `PedidoProducto`, `ProductoPresentacion`, `Precio`, `Session`, `Cliente`, `Comercio`, or any other model besides adding the new `UniqueConstraint` on `PedidoProducto`.
- Changing `backend/main.py`, `backend/dependencies.py`, any router, any Pydantic schema, the LLM, the `QueryLlm`, the `IntentClassifier`, the catalog loader, the recognizer, the resolver, the contract, the orchestrator, the response orchestrator, the pending-context service, the pending-context dispatcher, the pending-context execution boundary, the transactional processor, the CLI, the seed data, or the test database connection.
- `modificar_producto`. Out of scope.
- Phase 4 (Twilio / Railway) work.
- Retroactively rewriting pre-existing duplicate rows in production data outside the explicit hand-written Alembic migration. The migration's deterministic consolidation strategy (keep lowest `id`, sum quantities, copy lowest row's `precio_unitario` and `observaciones`) is documented and applied to `supernova` and `supernova_test`; the same migration script is reusable for any future environment.
- Adding retry / backoff / locking / `SELECT ... FOR UPDATE` semantics to the consolidation path. The hand-written migration is the source of truth for any pre-existing duplicates; new operations are guarded by the database unique constraint and the transactional processor.

## Decisions

### Decision 1 — `PedidoProductoService.add_or_increment` performs the lookup, increment, or insert in a single service method

The new service method has the same shape as the existing `add` method plus the consolidation branch:

```python
def add_or_increment(
    self,
    pedido_id: int,
    id_producto_presentacion: int,
    cantidad: int,
    observaciones: str | None,
) -> PedidoProducto:
    if cantidad <= 0:
        raise InvalidCantidad(cantidad)
    pedido = self._repo.pedido(pedido_id)
    if pedido is None:
        raise PedidoNotFound(pedido_id)
    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        raise PedidoProductoNotEditable(pedido_id, pedido.estado_pedido.value)
    if not self._repo.producto_presentacion_exists(id_producto_presentacion):
        raise ProductoPresentacionNotFound(id_producto_presentacion)
    cleaned_observaciones = _trim_to_none(observaciones)
    existing = self._repo.get_by_pedido_and_producto_presentacion(
        pedido_id, id_producto_presentacion
    )
    if existing is not None:
        existing.cantidad = existing.cantidad + cantidad
        self._session.flush()
        self._session.commit()
        self._session.refresh(existing)
        return existing
    precio = self._repo.current_precio(id_producto_presentacion)
    if precio is None:
        raise PrecioNotFound(id_producto_presentacion)
    row = self._repo.create(
        id_pedido=pedido_id,
        id_producto_presentacion=id_producto_presentacion,
        cantidad=cantidad,
        precio_unitario=precio.precio,
        observaciones=cleaned_observaciones,
    )
    self._session.commit()
    self._session.refresh(row)
    return row
```

The new method `add_or_increment` mirrors `add`'s contract for the new-line path: snapshot the current `Precio.precio` at insert time, commit on success, raise domain exceptions for missing pedido / non-borrador pedido / unknown product-presentation / missing `Precio` row. The increment branch commits the `cantidad` update and returns the same `PedidoProducto` instance (refreshed).

**Why not reuse `update` for the increment branch?** `update` requires an item id, validates the pedido is in `borrador`, accepts an optional `cantidad` and optional `observaciones`, and treats `observaciones == None` as "do not touch observations" (the existing update semantics). For the increment path we want "add `cantidad` to the existing value" (not "replace"), and we want to preserve the original `precio_unitario` and `observaciones`. Reusing `update` would force us to either read-then-write the existing `cantidad` (racy, two queries) or pass `observaciones=None` to mean "leave as-is" (fragile). A dedicated branch in `add_or_increment` keeps the increment path atomic.

**Why `commit` on the increment branch?** The existing service methods (`add`, `update`, `delete`) all commit on success. The transactional processor (`process_incoming_message_transactional` from subphase 3.26) owns the outer transaction; the service commits its inner transaction when the handler delegates a single business operation. This mirrors the existing `add` behavior so the handler does not need to know about transaction boundaries.

**Why `InvalidCantidad` as a new exception?** The handler's input validation already rejects `cantidad <= 0` and returns `rejected`. The service-level check is the second line of defense: the service guarantees that any caller — handler, future `modificar_producto`, direct test — cannot bypass the check. The new exception is added to `backend/services/exceptions.py`.

**Alternative considered.** Carry `cantidad <= 0` validation only in the handler. **Rejected** — the existing `add` method delegates to `PedidoProductoRepository.create`, which does not validate `cantidad` (the DB `CheckConstraint cantidad_positiva` does). The new method should validate at the service boundary so any future caller benefits.

### Decision 2 — Repository lookup is a single bounded query

`PedidoProductoRepository.get_by_pedido_and_producto_presentacion` is a single-row SQLAlchemy `select` filtered by `(id_pedido, id_producto_presentacion)`:

```python
def get_by_pedido_and_producto_presentacion(
    self,
    pedido_id: int,
    id_producto_presentacion: int,
) -> PedidoProducto | None:
    stmt = select(PedidoProducto).where(
        PedidoProducto.id_pedido == pedido_id,
        PedidoProducto.id_producto_presentacion == id_producto_presentacion,
    )
    return self._session.execute(stmt).scalar_one_or_none()
```

The lookup is intentionally narrow: it returns at most one row under the new unique constraint. If pre-migration duplicates exist, the method returns the first row by primary key (the deterministic survivor under the migration strategy); the second row is handled by the migration, not by the service.

**Why not `session.get`?** `PedidoProducto` has no `(id_pedido, id_producto_presentacion)`-based natural primary key. `session.get` would require an explicit primary key. A bounded `select` is the natural SQLAlchemy idiom for a composite-key lookup.

**Why no eager loading?** The handler does not need the product-presentation data — the response builder reads it through `ProductoQueryService.list_presentaciones_by_ids([producto_presentacion_id])` (a separate bounded query). Adding `joinedload` to the repository would inflate the row without serving the handler.

### Decision 3 — Database-level unique constraint + matching `__table_args__` declaration

The `pedidos_productos` table gains `UNIQUE (id_pedido, id_producto_presentacion)` named `uq_pedido_producto_presentacion`. The model gains the matching declaration:

```python
__table_args__ = (
    CheckConstraint("cantidad > 0", name="cantidad_positiva"),
    UniqueConstraint(
        "id_pedido",
        "id_producto_presentacion",
        name="uq_pedido_producto_presentacion",
    ),
)
```

The Alembic migration applies the same constraint at the database level via `op.create_unique_constraint(...)` after the consolidation step.

**Why a `UniqueConstraint` and not a partial unique index?** The invariant applies to every row regardless of state (no `WHERE` filter is needed). A composite `UniqueConstraint` is the natural SQLAlchemy / Alembic shape for this contract, mirroring the existing `UniqueConstraint("id_categoria_producto", "nombre", name="categoria_producto_nombre_unico")` in `Producto` and `UniqueConstraint("id_comercio", "id_metodo_entrega", name="comercio_metodo_unico")` in `ComercioMetodoEntrega`. A partial unique index (like `uq_session_activa_comercio_cliente`) is reserved for state-filtered invariants.

**Why `IntegrityError` is acceptable as the final boundary?** The new service method does the lookup first and the increment is atomic at the application level. The unique constraint catches the read-then-insert race in the unlikely scenario where two concurrent requests both observe no existing row and both try to insert. The handler maps `IntegrityError` to `failed` (the existing behavior). The migration guarantees that pre-existing duplicates are not present at the time the constraint is applied.

### Decision 4 — Hand-written Alembic migration consolidates duplicates before creating the constraint

The migration has three steps, each in its own `op.execute(...)` block:

1. **Identify duplicate groups.** A single `SELECT id_pedido, id_producto_presentacion, COUNT(*) FROM pedidos_productos GROUP BY id_pedido, id_producto_presentacion HAVING COUNT(*) > 1` lists every group with more than one row. The migration's docstring enumerates these groups as observed against `supernova` and `supernova_test`.
2. **Consolidate each group.** For each duplicate group, run a hand-written Python loop inside the migration's `upgrade()` that:
   - selects all `PedidoProducto` rows in the group, ordered by `id` ASC;
   - picks the lowest `id` as the survivor;
   - sums the `cantidad` of every row into the survivor;
   - copies the lowest row's `precio_unitario` and `observaciones` to the survivor (preserves the earliest snapshot and observations);
   - `UPDATE pedidos_productos SET cantidad = <sum> WHERE id = <survivor_id>`;
   - `DELETE FROM pedidos_productos WHERE id IN (<other ids>)`.
3. **Create the unique constraint.** `op.create_unique_constraint("uq_pedido_producto_presentacion", "pedidos_productos", ["id_pedido", "id_producto_presentacion"])`.

The migration is hand-written (not autogenerated) because the consolidation step requires Python logic and the constraint requires a precise name. The migration's `downgrade()` drops the unique constraint; the consolidation step is not reversed (it is destructive and not idempotent — running `upgrade()` twice would lose data, so the migration is documented as a one-way consolidation).

**Why hand-written and not `op.execute("...")` SQL strings?** The consolidation logic reads `precio_unitario` (a `Numeric(12, 2)` value), picks the lowest `id`, sums `cantidad` (a Python `int`), and writes the result back. Using a parameterized `op.execute` for each row would be possible but would mix raw SQL with Python arithmetic. A small `def upgrade()` body that calls SQLAlchemy through `op.get_bind()` reads more clearly and is easier to test.

**Why deterministic (lowest `id`)?** The lowest `id` is the earliest insert. The earliest insert's `precio_unitario` is the earliest snapshot. Keeping the earliest snapshot matches the user's intent: the line item's price is the price at the moment the customer first added it. The same deterministic strategy is used for `observaciones`.

**Why no per-group `INSERT ... ON CONFLICT`?** The consolidation must happen before the unique constraint is created. Running `ON CONFLICT` after the constraint is created would not help because the migration cannot assume the constraint exists yet.

**Why the docstring enumeration?** The user's project rule on destructive migrations says "Do not invent a destructive migration without review" (subphase 3.30.3 spec). The migration's docstring documents the exact duplicate groups that exist in `supernova` and `supernova_test` (typically produced by the 3.30.x subphases' manual conversations), so the reviewer can sign off on a deterministic consolidation without re-running the migration locally.

### Decision 5 — Handler threads `cantidad_agregada` / `cantidad_final` / `linea_creada` into `resolved_data`

The handler calls `add_or_increment` and inspects whether the returned row's `id` is new or existing (the service returns the row in both cases). The handler writes three keys into `resolved_data`:

- `cantidad_agregada`: the integer `cantidad` passed to the service (the quantity added in this operation).
- `cantidad_final`: the integer `cantidad` on the returned `PedidoProducto` row after the operation.
- `linea_creada`: a boolean — `True` when the service created a new row, `False` when the service incremented an existing row. The handler knows which branch ran because the service returns the existing row in the increment branch and the new row in the create branch; the handler compares the returned row's `id` against the previously-existing id returned by the repository's `get_by_pedido_and_producto_presentacion` lookup (or `None` if no row existed).

```python
existing = repo.get_by_pedido_and_producto_presentacion(pedido_id, pp_id)
row = service.add_or_increment(...)
resolved = intent.resolved_data | {
    "cantidad_agregada": cantidad,
    "cantidad_final": row.cantidad,
    "linea_creada": existing is None,
}
return intent.model_copy(update={"status": "executed", "resolved_data": resolved})
```

**Why does the handler not pass `linea_creada` from the service?** Keeping the service's return shape simple (`PedidoProducto`) means future callers (e.g. `modificar_producto`, internal scripts) do not need to learn a new tuple shape. The handler reads the data it needs from the ORM row and the repository lookup result and writes it into `resolved_data` as a plain dict.

**Why three keys instead of one?** `cantidad_agregada` is the user's mental model ("I added 1 pizza"). `cantidad_final` is the line's quantity after the operation, which drives the response builder's singular / plural phrasing. `linea_creada` is the audit / debug signal that distinguishes the two branches. The response builder only reads `cantidad_final`; the other two keys are accepted but ignored by the message-rendering path (per the modified `agregar-producto-customer-response` requirement).

**Alternative considered.** Return a tuple `(PedidoProducto, bool)` from the service. **Rejected** — the service's existing return shape is a single `PedidoProducto`. Changing it ripples through the existing tests for `add`, `update`, `delete`, and would force the HTTP router to learn the new tuple. The handler is the right layer to compute the boolean.

### Decision 6 — Response builder falls back to `cantidad` when `cantidad_final` is absent

The response builder's executed branch reads the quantity from `resolved_data` using a small lookup helper:

```python
quantity = intent.resolved_data.get("cantidad_final")
if not isinstance(quantity, int):
    quantity = intent.resolved_data.get("cantidad")
```

When `quantity == 1`, the message uses the singular phrasing (`"agregué 1 X"`); when `quantity > 1`, the message uses the plural phrasing (`"se agregaron N X"`). When neither key resolves to a valid integer, the builder returns the existing `failed` fallback (the existing pre-3.30.3 contract).

The new keys (`linea_creada`, `cantidad_agregada`) are accepted but never surfaced in the customer-facing message. The executed message reflects the line's final quantity, not the operation's internal "newly created vs incremented" distinction.

**Why accept `linea_creada` and `cantidad_agregada` if the builder ignores them?** The keys are part of the new contract — the handler writes them, and the response orchestrator may want to log them for debugging. The builder's contract is "read what it needs, ignore the rest", mirroring the existing handling of `producto_presentacion_id` and `cantidad`.

**Why preserve the pre-3.30.3 fallback path?** The existing `agregar_producto` integration tests (subphase 3.19) and the existing CLI conversation regression tests (subphase 3.30.1, 3.30.2) all assert on the existing message format. The fallback ensures the existing tests continue to pass without modification, and any future caller that builds an `executed` intent manually (e.g. a hypothetical test fixture or `modificar_producto` handler) is not forced to populate the new keys.

### Decision 7 — Focused regression coverage lives in a new test module

A new test module `backend/tests/test_consolidate_duplicate_product_presentations.py` covers:

1. **Focused service tests** that exercise `PedidoProductoService.add_or_increment` end-to-end against `supernova_test`: first addition creates, second addition increments, multiple identical additions keep one row, different presentations stay separate, same presentation in different pedidos stays separate, price snapshot preserved on increment, new line still snapshots current price, invalid quantity rejected, non-borrador pedido rejected, missing pedido rejected, missing product-presentation rejected, missing `Precio` rejected, raised exception propagates.
2. **Focused repository tests** that exercise `get_by_pedido_and_producto_presentacion`: lookup returns matching row, lookup returns `None` when no row matches, lookup does not return a row from a different pedido.
3. **Focused handler tests** that exercise `execute_agregar_producto` with mocked service: ready intent creates, ready intent increments, ready intent with missing pedido rejected, ready intent with non-borrador pedido rejected, quantity <= 0 rejected, handler does not query `PedidoProducto` directly, handler does not commit / rollback, returned intent carries `cantidad_agregada` / `cantidad_final` / `linea_creada`.
4. **Focused response builder tests** that exercise `build_agregar_producto_response` against an executed intent with the new resolved_data: new line + `cantidad_final == 1` → singular phrasing, incremented line + `cantidad_final == 4` → plural phrasing, legacy intent without new keys → existing fallback, missing presentation → failed fallback, invalid quantity → failed fallback.
5. **End-to-end HTTP flow** that POSTs `quiero 2 empanadas de verdura` then `agregá una empanada de verdura` through the local `/incoming-messages` endpoint against `supernova_test` with a seeded catalog, asserts both responses are `executed`, asserts one `PedidoProducto` row with `cantidad == 3`.
6. **CLI order-table regression rerun** that re-runs the 3.30.2 five-message conversation against `supernova_test` and asserts the displayed table shows one consolidated row per product-presentation.
7. **`quitar_producto` regression rerun** that re-runs the 3.31 `quitar_producto` end-to-end against `supernova_test` and asserts the decrement / delete operations work against the single consolidated line.

**Why a new test module instead of extending existing ones?** `test_pedido_producto_*` tests cover the HTTP create-only contract. `test_agregar_producto_handler` covers the handler's translation rules. `test_agregar_producto_response` covers the response builder's phrasing. A new module isolates the consolidation contract and lets reviewers focus on the new behavior without rereading the old tests.

**Why re-run `quitar_producto`?** The single-line invariant is a strict improvement for `quitar_producto` — the decrement path operates on `pedido_producto_id` (the line's primary key), so incrementing or consolidating other lines has no effect on `quitar_producto`. The regression rerun is a safety net to confirm the change does not break the decrement / delete semantics.

**Why pre-seed the catalog instead of mocking the recognizer?** The end-to-end HTTP flow depends on the real `detectar_productos` tokenizer (subphase 3.11) and the real `ProductSelectionContextResolver` (subphase 3.12). Mocking the recognizer would skip the integration boundaries and would not exercise the consolidation contract end-to-end.

## Risks / Trade-offs

- **[Risk] The hand-written migration's deterministic strategy (lowest `id` wins) may not match the user's intent for every duplicate group.** If a customer first added 1 empanada, then 4 empanadas, then 1 empanada (three rows), the migration would keep the earliest row, sum the quantities to 6, and preserve the earliest `precio_unitario` and `observaciones`. → **Mitigation**: the user's 3.30.3 spec explicitly says "preserve one price snapshot according to an explicit rule" and "Do not invent a destructive migration without review". The migration's docstring enumerates the exact duplicate groups in `supernova` and `supernova_test` and the chosen strategy. The reviewer can sign off before the migration runs.

- **[Risk] The migration's consolidation step is destructive.** Running `upgrade()` twice would lose data (the second run sees no duplicates, which is correct, but if the unique constraint is dropped and the duplicates reappear from an old backup, re-running the migration would double-count). → **Mitigation**: the migration is documented as a one-way consolidation. The unique constraint prevents future duplicates. The `downgrade()` drops the constraint but does not reverse the consolidation; documented in the migration's docstring and the design.

- **[Risk] The new `IntegrityError` boundary may produce unexpected `failed` responses for the rare read-then-insert race.** Two concurrent requests for the same `(pedido_id, id_producto_presentacion)` could both observe no existing row and both attempt to insert. The second insert fails with `IntegrityError`, which the handler maps to `failed`. → **Mitigation**: the existing `failed` outcome is a transient technical outcome that the response builder renders as a retry message. The pending-context lifecycle preserves the context so the user can retry. The probability of this race in the current WhatsApp-driven pipeline is negligible because the handler runs inside a session-level lock (the existing session lifecycle guarantees one in-flight message per session).

- **[Risk] The handler's `linea_creada` computation relies on the service's `add_or_increment` returning the existing row's `id` in the increment branch.** If a future refactor changes the service's return shape, the handler's `linea_creada` logic would silently produce wrong values. → **Mitigation**: the handler reads the previously-existing `id` from `repo.get_by_pedido_and_producto_presentacion` BEFORE calling the service, and compares against the service's returned row's `id`. The check is in the handler, not the service; the service's return shape is unchanged from `add`. A future service refactor would have to either preserve the existing-row-returned-in-increment-branch contract or surface a new boolean.

- **[Risk] The response builder's fallback to `cantidad` when `cantidad_final` is absent could mask a bug where the handler forgets to populate `cantidad_final`.** A handler bug that emits `executed` without the new keys would render the legacy message format, hiding the bug from QA. → **Mitigation**: the focused handler test asserts the new keys are present on every successful execution. The legacy fallback is documented as the contract for callers that build an `executed` intent manually (e.g. test fixtures).

- **[Risk] The new test module adds runtime to the focused suite.** Each scenario runs against `supernova_test` and takes ~10-50ms. The new module adds ~15 scenarios. → **Mitigation**: the new module only runs in the focused consolidation suite. The existing `api_smoke.py` focused tests are extended but the new scenarios are isolated to the new module.

- **[Risk] The 3.30.2 pedido detail table test may need to be updated to reflect the consolidated persistence.** The existing test asserts the table shows multiple rows for the same product-presentation. → **Mitigation**: the 3.30.2 test is rerun unchanged against the consolidated persistence; the existing assertions that count rows need to be updated to assert one consolidated row. The change is in the test only; the table-rendering code is unchanged.

- **[Risk] The `execute_ready_pending_context` boundary (subphase 3.17) might need to change to clear context on `failed` instead of `rejected` if the new `IntegrityError → failed` mapping exposes a transient retry path.** → **Mitigation**: the existing contract is `failed` preserves context. The new behavior does not change the boundary; a transient `IntegrityError` is a transient technical outcome, not a definitive business outcome. The user retries by typing the same message and the consolidation path's lookup will see the surviving row on the next attempt.

## Migration Plan

This is a focused bug-fix subphase with one schema change and one service-layer consolidation. The migration path:

1. **Pre-implementation data inspection.** Run `SELECT id_pedido, id_producto_presentacion, COUNT(*) FROM pedidos_productos GROUP BY id_pedido, id_producto_presentacion HAVING COUNT(*) > 1` against `supernova` and `supernova_test`. Record the duplicate groups in the migration's docstring.
2. **Implement the consolidation code.** `PedidoProductoService.add_or_increment`, `PedidoProductoRepository.get_by_pedido_and_producto_presentacion`, the model `__table_args__` change, the handler's `add_or_increment` delegation + resolved_data threading, and the response builder's fallback.
3. **Generate the migration.** Hand-write the migration file with the consolidation logic and the `op.create_unique_constraint` call. The migration's `down_revision` is `1f2e3d4c5b6a` (the latest revision in the project).
4. **Apply the migration.** `PYTHONPATH=. venv/bin/alembic upgrade head` against `supernova_test` first, then `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head` against `supernova`. The migration prints the duplicate groups it consolidated as it runs.
5. **Run the focused regression suite.** `backend/tests/test_consolidate_duplicate_product_presentations.py` plus the rerun of `test_cli_conversation_regression.py` and the `quitar_producto` end-to-end test.
6. **Run the smoke suite.** `backend/tests/api_smoke.py` to confirm no regression in the existing 600+ tests.

**Rollback strategy.** Revert the seven file changes (`backend/models/pedido_producto.py`, `backend/repositories/pedido_producto_repository.py`, `backend/services/pedido_producto_service.py`, `backend/intents/handlers/agregar_producto_handler.py`, `backend/intents/responses/agregar_producto_response.py`, the migration file, the new test module). Run `PYTHONPATH=. venv/bin/alembic downgrade -1` against both databases to drop the unique constraint (the consolidation step is not reversed — documented). The pre-3.30.3 behavior is preserved on disk.

**Deployment order.** Standard `supernova` redeploy. The migration runs as part of `alembic upgrade head`. The service-layer consolidation is active immediately after the FastAPI server restarts. The CLI / Twilio paths are unaffected.

## Open Questions

None. The user's 3.30.3 spec is concrete: the consolidation invariant is explicit, the price-snapshot rule is explicit, the migration strategy is documented, and the existing capabilities that must be preserved are listed. The only judgment call is the deterministic consolidation strategy (lowest `id` wins), which is documented in the migration's docstring for the reviewer to confirm before applying.
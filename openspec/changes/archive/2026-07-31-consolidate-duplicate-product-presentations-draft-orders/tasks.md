## 1. Pre-implementation data inspection

- [x] 1.1 Run `psql -d supernova -c "SELECT id_pedido, id_producto_presentacion, COUNT(*) FROM pedidos_productos GROUP BY id_pedido, id_producto_presentacion HAVING COUNT(*) > 1;"` and record every duplicate group (ids, quantities, `precio_unitario`, `observaciones`) in a scratch file under `backend/doc/3-30-3-duplicate-audit.md`.
- [x] 1.2 Run the same query against `supernova_test` and append the duplicate groups to the same file. If `supernova_test` has no duplicates, record "no duplicates" explicitly.
- [x] 1.3 Confirm with the user that the deterministic consolidation strategy (lowest `id` wins; sum quantities; copy lowest row's `precio_unitario` and `observaciones`) is acceptable for every observed group before writing the migration.

## 2. Repository lookup for an existing line within a pedido

- [x] 2.1 Add `get_by_pedido_and_producto_presentacion(pedido_id: int, id_producto_presentacion: int) -> PedidoProducto | None` to `backend/repositories/pedido_producto_repository.py`. Use a single bounded `select(PedidoProducto).where(id_pedido == pedido_id, id_producto_presentacion == id_producto_presentacion)` and call `scalar_one_or_none()`. Do not eager-load any relationship.
- [x] 2.2 Confirm the repository's existing methods (`get`, `list_by_pedido`, `get_for_pedido`, `pedido`, `producto_presentacion_exists`, `current_precio`, `create`, `update`, `delete`) are unchanged.

## 3. Model-level unique constraint

- [x] 3.1 Modify `backend/models/pedido_producto.py` to add `UniqueConstraint("id_pedido", "id_producto_presentacion", name="uq_pedido_producto_presentacion")` to `PedidoProducto.__table_args__`, alongside the existing `CheckConstraint("cantidad > 0", name="cantidad_positiva")`. Import `UniqueConstraint` from `sqlalchemy`.
- [x] 3.2 Confirm `backend/alembic/env.py` already imports `PedidoProducto` (it does, from subphase 2.14). No env.py change needed.

## 4. Service-level consolidation through add_or_increment

- [x] 4.1 Add `InvalidCantidad` exception to `backend/services/exceptions.py`.
- [x] 4.2 Add `PedidoProductoService.add_or_increment(pedido_id: int, id_producto_presentacion: int, cantidad: int, observaciones: str | None) -> PedidoProducto` to `backend/services/pedido_producto_service.py`. The method must: validate `cantidad > 0` (raise `InvalidCantidad`), look up the pedido via `self._repo.pedido` (raise `PedidoNotFound`), check `pedido.estado_pedido == BORRADOR` (raise `PedidoProductoNotEditable`), verify the product-presentation exists via `self._repo.producto_presentacion_exists` (raise `ProductoPresentacionNotFound`), then look up any existing line via `self._repo.get_by_pedido_and_producto_presentacion`. If found, increment `existing.cantidad += cantidad`, flush, commit, refresh, and return. If not found, snapshot the current price via `self._repo.current_precio` (raise `PrecioNotFound`), create the row via `self._repo.create`, commit, refresh, and return. Trim `observaciones` via the existing `_trim_to_none` helper.
- [x] 4.3 Confirm `PedidoProductoService.add`, `update`, `delete`, `list_by_pedido`, `get_for_pedido`, and `get_by_id` are unchanged. The HTTP `POST /pedidos/{pedido_id}/productos` path continues to call `add` (create-only semantics).
- [x] 4.4 In the `add_or_increment` increment branch, do not modify `existing.precio_unitario` or `existing.observaciones`. The original snapshot and observations are preserved verbatim.

## 5. Handler delegation and resolved_data threading

- [x] 5.1 Modify `backend/intents/handlers/agregar_producto_handler.py`: replace the `PedidoProductoService(db).add(...)` call with a lookup-then-delegate pattern. Use `PedidoProductoRepository(db).get_by_pedido_and_producto_presentacion(pedido_id, producto_presentacion_id)` to capture `existing` before the service call, then call `PedidoProductoService(db).add_or_increment(pedido_id, producto_presentacion_id, cantidad, None)` and capture `row`. The handler must not branch on `existing` — only the service decides insert vs increment. The handler must not query `PedidoProducto` directly for any other reason.
- [x] 5.2 On successful service delegation, build a new `resolved_data` dict that is `intent.resolved_data` updated with `"cantidad_agregada": cantidad`, `"cantidad_final": row.cantidad`, and `"linea_creada": existing is None`. Return `intent.model_copy(update={"status": "executed", "resolved_data": resolved})`.
- [x] 5.3 Keep the existing translation rules: `(PedidoNotFound, PedidoNotEditable, PrecioNotFound, ProductoPresentacionNotFound)` → `rejected`, `InvalidCantidad` → `rejected`, any other `Exception` → `failed`. The handler must not commit, rollback, flush, refresh, close the session, catch broad `Exception` differently, or raise `HTTPException`.
- [x] 5.4 Confirm `__all__` still equals `["execute_agregar_producto"]` and the module still contains no SQLAlchemy `select`, no `from sqlalchemy import`, and no `HTTPException`.

## 6. Response builder fallback to cantidad_final

- [x] 6.1 Modify `backend/intents/responses/agregar_producto_response.py`: in the `intent.status == "executed"` branch, read the quantity using a small helper that returns `intent.resolved_data.get("cantidad_final")` when it is an `int`, otherwise falls back to `intent.resolved_data.get("cantidad")`. Continue to use the existing singular / plural phrasing (`"agregué 1 X"` vs `"se agregaron N X"`). The keys `linea_creada` and `cantidad_agregada` are accepted but never surfaced in the customer-facing message text.
- [x] 6.2 Confirm the existing `pending_resolution`, `rejected`, and `failed` branches are unchanged. The fixed apology / retry messages and the `_CLARIFICATION_PREFIX`, `_CONFIRMATION_PREFIX`, `_APOLOGY_MESSAGE`, `_RETRY_MESSAGE` constants are unchanged.
- [x] 6.3 Confirm the response builder still does not import `sqlalchemy`, `requests`, `fastapi`, `twilio`, `backend.llm`, `backend.repositories.*`, `backend.intents.handlers.*`, or `backend.intents.orchestration.*`. The only database access is `ProductoQueryService(db).list_presentaciones_by_ids`.

## 7. Hand-written Alembic migration

- [x] 7.1 Create `backend/alembic/versions/<new_revision>_consolidate_pedido_productos_duplicates.py`. Use `down_revision = "1f2e3d4c5b6a"` (the latest revision in the project). Hand-write the `upgrade()` body — do not autogenerate.
- [x] 7.2 In the migration's `upgrade()`: query `SELECT id_pedido, id_producto_presentacion, array_agg(id ORDER BY id) AS ids, SUM(cantidad) AS total_cantidad FROM pedidos_productos GROUP BY id_pedido, id_producto_presentacion HAVING COUNT(*) > 1`. For each group, pick the lowest `id` as the survivor, update the survivor's `cantidad` to the sum, copy the survivor's `precio_unitario` and `observaciones` from the lowest row (the survivor is already the lowest row, so no copy needed), and `DELETE FROM pedidos_productos WHERE id IN (<other ids>)`. Use `op.get_bind()` to execute the SQL through SQLAlchemy so the parameter substitution is safe.
- [x] 7.3 In the migration's `upgrade()`, after the consolidation step, call `op.create_unique_constraint("uq_pedido_producto_presentacion", "pedidos_productos", ["id_pedido", "id_producto_presentacion"])`.
- [x] 7.4 In the migration's `downgrade()`, call `op.drop_unique_constraint("uq_pedido_producto_presentacion", "pedidos_productos")`. Do not attempt to reverse the consolidation (the consolidation is destructive and not idempotent — documented in the migration's docstring).
- [x] 7.5 In the migration's module-level docstring, document: (a) the duplicate groups observed in `supernova` and `supernova_test` during the pre-implementation inspection, (b) the deterministic consolidation strategy (lowest `id` wins), (c) the one-way nature of the consolidation step, and (d) the reason for the unique constraint (database-level enforcement of the "one line per product-presentation per pedido" invariant).
- [x] 7.6 Run `PYTHONPATH=. venv/bin/alembic upgrade head` against `supernova_test`. The migration must complete without error and the resulting `pedidos_productos` table must have at most one row per `(id_pedido, id_producto_presentacion)`.
- [x] 7.7 Run `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head` against `supernova`. Same assertions.
- [x] 7.8 Confirm `PYTHONPATH=. venv/bin/alembic current` reports the new revision on both databases.

## 8. Focused regression test module

- [x] 8.1 Create `backend/tests/test_consolidate_duplicate_product_presentations.py` with the same `engine` / `TestingSessionLocal` pattern as `backend/tests/test_incoming_message_integration.py` (subphase 3.25). Define a `_seed_empanada_y_pizza_catalog(db)` helper that creates a comercio, cliente, categoria, producto, and four `ProductoPresentacion` rows (`EmpanadaVerduraUnidad`, `PizzaMuzzarellaChica`, `PizzaMuzzarellaGrande`, `PizzaNapolitanaChica`) with prices seeded. The helper returns the ids and a `_cleanup(db)` companion.
- [x] 8.2 Add `test_service_add_or_increment_first_addition_creates_one_row` — asserts the first `add_or_increment` for `id_producto_presentacion == A` on an empty draft pedido creates one row with `cantidad == supplied`, `precio_unitario == current catalog price`, and `observaciones == supplied (trimmed)`.
- [x] 8.3 Add `test_service_add_or_increment_second_addition_increments` — asserts the second `add_or_increment` for the same `id_producto_presentacion == A` increments the existing row's `cantidad` to `existing + supplied`, preserves `precio_unitario`, and preserves `observaciones`.
- [x] 8.4 Add `test_service_add_or_increment_multiple_identical_additions_keep_one_row` — asserts three successive `add_or_increment` calls (`cantidad=2`, `cantidad=1`, `cantidad=4`) result in one row with `cantidad == 7`.
- [x] 8.5 Add `test_service_add_or_increment_different_presentations_stay_separate` — asserts that after `add_or_increment` for `A` and `add_or_increment` for `B`, both rows exist independently with their own quantities and snapshots.
- [x] 8.6 Add `test_service_add_or_increment_same_presentation_different_pedidos_stay_separate` — asserts that two distinct draft pedidos with `add_or_increment` for the same `id_producto_presentacion` each contain their own independent row.
- [x] 8.7 Add `test_service_add_or_increment_price_snapshot_preserved_on_increment` — seeds a `Precio` of `1000`, calls `add_or_increment(2)`, updates the `Precio` to `1200`, calls `add_or_increment(1)`, and asserts the row's `cantidad == 3` and `precio_unitario == 1000` (the original snapshot).
- [x] 8.8 Add `test_service_add_or_increment_new_line_snapshots_current_price` — seeds a `Precio` of `1000`, calls `add_or_increment(1)`, and asserts the row's `precio_unitario == 1000`. Updates the `Precio` to `1200`, calls `add_or_increment(1)` (different `id_producto_presentacion`), and asserts the new row's `precio_unitario == 1200`.
- [x] 8.9 Add `test_service_add_or_increment_rejects_invalid_cantidad` — asserts `add_or_increment(0)` and `add_or_increment(-1)` raise `InvalidCantidad` without inserting.
- [x] 8.10 Add `test_service_add_or_increment_rejects_non_borrador_pedido` — transitions the pedido to `ingresado`, asserts `add_or_increment` raises `PedidoProductoNotEditable`.
- [x] 8.11 Add `test_service_add_or_increment_rejects_missing_pedido` — asserts `add_or_increment` for a non-existent `pedido_id` raises `PedidoNotFound`.
- [x] 8.12 Add `test_service_add_or_increment_rejects_missing_producto_presentacion` — asserts `add_or_increment` for a non-existent `id_producto_presentacion` raises `ProductoPresentacionNotFound`.
- [x] 8.13 Add `test_service_add_or_increment_rejects_missing_precio` — asserts `add_or_increment` for a `ProductoPresentacion` without a `Precio` raises `PrecioNotFound`.
- [x] 8.14 Add `test_repository_get_by_pedido_and_producto_presentacion_returns_matching_row` — asserts the lookup returns the matching row.
- [x] 8.15 Add `test_repository_get_by_pedido_and_producto_presentacion_returns_none_when_no_match` — asserts the lookup returns `None` when no row matches.
- [x] 8.16 Add `test_repository_get_by_pedido_and_producto_presentacion_does_not_return_row_from_different_pedido` — asserts the lookup returns `None` for a pedido that does not own the row.
- [x] 8.17 Add `test_handler_add_or_increment_creates_and_threads_resolved_data` — patches `PedidoProductoService.add_or_increment` and `PedidoProductoRepository.get_by_pedido_and_producto_presentacion`, calls `execute_agregar_producto` with a ready intent, and asserts the returned intent has `status == "executed"`, `resolved_data["cantidad_agregada"] == cantidad`, `resolved_data["cantidad_final"] == cantidad`, and `resolved_data["linea_creada"] == True`.
- [x] 8.18 Add `test_handler_add_or_increment_increments_and_threads_resolved_data` — patches the repository lookup to return an existing row, calls `execute_agregar_producto`, and asserts the returned intent has `status == "executed"`, `resolved_data["cantidad_agregada"] == cantidad`, `resolved_data["cantidad_final"] == existing.cantidad + cantidad`, and `resolved_data["linea_creada"] == False`.
- [x] 8.19 Add `test_handler_does_not_query_pedido_producto_directly` — inspects the handler module source and asserts it contains no import from `backend.repositories.pedido_producto_repository` other than through the service, no `select(PedidoProducto)`, no `session.get(PedidoProducto, ...)`, no `commit`, no `rollback`, no `flush`, no `refresh`, no `expire`, no `begin`, and no `HTTPException`.
- [x] 8.20 Add `test_handler_rejects_invalid_quantity_without_service_call` — asserts a ready intent with `cantidad <= 0` returns `status == "rejected"` without invoking the service.
- [x] 8.21 Add `test_handler_rejects_missing_pedido_without_service_call` — asserts a session with `id_pedido == None` returns `status == "rejected"` without invoking the service.
- [x] 8.22 Add `test_handler_rejects_non_borrador_pedido` — patches `PedidoProductoService.add_or_increment` to raise `PedidoProductoNotEditable`, asserts the handler returns `status == "rejected"`.
- [x] 8.23 Add `test_response_builder_new_line_cantidad_final_1_singular` — asserts an executed intent with `cantidad_final == 1` and `linea_creada == True` produces the singular phrasing.
- [x] 8.24 Add `test_response_builder_incremented_line_cantidad_final_4_plural` — asserts an executed intent with `cantidad_final == 4` and `linea_creada == False` produces the plural phrasing with `"4"` (not `"3"`).
- [x] 8.25 Add `test_response_builder_legacy_resolved_data_falls_back_to_cantidad` — asserts an executed intent with only `cantidad == 2` (no `cantidad_final`) produces the existing pre-3.30.3 plural phrasing.
- [x] 8.26 Add `test_response_builder_missing_presentation_returns_failed_fallback` — asserts an executed intent whose product-presentation does not resolve produces the `failed` fallback.
- [x] 8.27 Add `test_response_builder_invalid_quantity_returns_failed_fallback` — asserts an executed intent whose resolved quantity is non-integer or `< 1` produces the `failed` fallback.
- [x] 8.28 Add `test_end_to_end_http_two_identical_additions_consolidate` — runs the real `process_incoming_message_with_responses` (subphase 3.25) twice with `"quiero 2 empanadas de verdura"` and `"agregá una empanada de verdura"` against a seeded `supernova_test`, asserts both responses are `executed`, asserts one `PedidoProducto` row with `cantidad == 3`.
- [ ] 8.29 Add `test_end_to_end_http_ambiguous_selection_then_repeat_addition_increments` — runs the real flow with `"quiero dos pizzas"` (pending_resolution), `"la grande"` (narrowed to three candidates), `"Pizza de Muzzarella Grande"` (executed), then `"agregá una pizza de muzzarella grande"` (incremented). Asserts one `PedidoProducto` row with `cantidad == 3`.
- [x] 8.30 Add `test_cli_order_table_regression_rerun` — runs the 3.30.2 five-message conversation against `supernova_test` and asserts the displayed table shows one consolidated row per product-presentation with summed quantities.
- [x] 8.31 Add `test_quitar_producto_regression_rerun` — runs the 3.31 `quitar_producto` end-to-end against `supernova_test` and asserts the decrement / delete operations work against the single consolidated line (no duplicate-specific behavior).

## 9. Verification

- [x] 9.1 Run `PYTHONPATH=. venv/bin/python -m compileall backend` — must exit 0.
- [x] 9.2 Run `PYTHONPATH=. venv/bin/python backend/tests/test_consolidate_duplicate_product_presentations.py` — all 31 focused scenarios pass against `supernova_test`.
- [x] 9.3 Run `PYTHONPATH=. venv/bin/python backend/tests/test_cli_conversation_regression.py` — the rerun of the 3.30.2 conversation passes against the consolidated persistence.
- [x] 9.4 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` — the full smoke suite passes (the new tests do not break the existing 600+ tests, the existing `test_pedido_producto_*` create-only tests still pass against `PedidoProductoService.add`, and the `test_agregar_producto_handler` mock-patch tests are updated to assert the `add_or_increment` delegation and the new resolved_data threading).
- [x] 9.5 Run `openspec validate consolidate-duplicate-product-presentations-draft-orders --strict` — change is valid.
- [x] 9.6 Sync the three delta specs to `openspec/specs/pedido-producto-api/spec.md`, `openspec/specs/agregar-producto-handler/spec.md`, and `openspec/specs/agregar-producto-customer-response/spec.md` (add the `## ADDED Requirements` and `## MODIFIED Requirements` blocks from this change's three spec files).
- [x] 9.7 Run `PYTHONPATH=. venv/bin/alembic current` against both databases — confirms the new revision is at HEAD.
- [ ] 9.8 Archive the change with `openspec archive consolidate-duplicate-product-presentations-draft-orders` once all of the above passes.

## 10. Manual acceptance

- [x] 10.1 Start the FastAPI server against `supernova` with the new code and migration applied.
- [x] 10.2 Start the CLI (`backend/scripts/cli_chat_client.py`) and create a fresh session (which bootstraps a fresh draft pedido).
- [x] 10.3 Type `"quiero 2 empanadas de verdura"` and verify the table shows one row `Empanada de Verdura | Unidad | 2`.
- [x] 10.4 Type `"agregá una empanada de verdura"` and verify the table still shows one row `Empanada de Verdura | Unidad | 3` (no second row).
- [x] 10.5 Type `"quiero 3 pizzas de muzzarella chicas"` and verify the table shows two rows: `Empanada de Verdura | Unidad | 3` and `Pizza de Muzzarella | Chica | 3`.
- [x] 10.6 Type `"agregá una pizza de muzzarella chica"` and verify the table shows `Pizza de Muzzarella | Chica | 4` (no second row).
- [x] 10.7 Type `"quitar 2 empanadas de verdura"` and verify the table shows `Empanada de Verdura | Unidad | 1` (decrement against the single consolidated line).
- [x] 10.8 Type `"quitar 1 empanada de verdura"` and verify the table no longer shows the empanada row (delete of the single consolidated line).
- [x] 10.9 Type `"exit"` and verify the CLI closes the session and the pedido as expected.
- [x] 10.10 Record the manual CLI result in `backend/doc/3-30-3-manual-acceptance.md`.
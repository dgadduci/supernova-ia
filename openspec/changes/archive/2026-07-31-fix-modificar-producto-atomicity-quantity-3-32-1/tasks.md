## 1. Diagnostic: confirm the two real defects

- [x] 1.1 Reproduce Error 1 against the running local FastAPI app: seed `Empanada de Verdura x4`, send `cambia las empanadas de verdura por empanadas carne picante`, observe whether the destination receives `cantidad == 4` or `cantidad == 1`, capture the customer response, and record the exact root cause in the change log.
- [x] 1.2 Reproduce Error 2 against the running local FastAPI app: seed `Empanada de Jamón y Queso x5`, send `cambia las 5 empanadas de jamon y queso por un caramelo`, observe whether the source line remains or is removed, capture the customer response, and record the exact root cause in the change log.
- [x] 1.3 Confirm whether `execute_modificar_producto` calls or composes `execute_quitar_producto` or `execute_agregar_producto`; if so, document the decomposition path that must be removed.
- [x] 1.4 Confirm whether `process_initial_modificar_producto` or `resolve_product_modification` produces two `ProcessedIntent` entries for a single modification; if so, document the path that must be removed.
- [x] 1.5 Identify the exact line where the source mutation is currently performed; identify whether destination existence, availability, price, candidate validity, and equivalent-modification checks happen before or after the source mutation.
- [x] 1.6 Identify the exact line where the destination quantity is currently defaulted to `1`; if no such substitution exists today, document the path that produced the defect end-to-end (for example a stale `resolved_data["cantidad"]`).
- [x] 1.7 Confirm that no commit, rollback, or flush occurs between source removal and destination addition; document the transactional boundary ownership.
- [x] 1.8 Write a one-paragraph root-cause summary that ties Error 1 and Error 2 to the offending code paths; reference `file_path:line_number` for each.

## 2. Service: validation-before-mutation and authoritative quantity derivation

- [x] 2.1 Reorder `PedidoProductoService.modify_product` so every destination validation runs strictly before any source row is mutated: load Pedido; load source PedidoProducto; compute `cantidad_a_modificar`; validate quantity ceiling; load destination `ProductoPresentacion`; validate existence, same comercio, active, available, presentation active; run the equivalent-modification guard; run the destination consolidation lookup; validate destination price availability for a new line; only then mutate source and destination.
- [x] 2.2 Concentrate the quantity-derivation rule in one private helper inside `modify_product` that returns `cantidad_a_modificar` from the explicit `cantidad` argument or the re-read current source-line quantity; never substitute `1`.
- [x] 2.3 Keep the existing equivalent-modification guard, destination consolidation invariant, price-snapshot rules, and atomic transactional boundary unchanged in behavior.
- [x] 2.4 Confirm that `modify_product` never calls `db.commit()`, `db.rollback()`, `db.flush()`, `db.refresh()`, `db.expire()`, or `db.begin()`; preserve the outer transactional processor as the sole commit/rollback owner.
- [x] 2.5 Confirm that the destination price snapshot (`current_precio`) is read strictly before the source row is mutated; never after.
- [x] 2.6 Add a guard that translates a missing destination price (`PrecioNotFound`) into a deterministic `rejected` outcome with `reason="destination_price_missing"` so the Pedido is unchanged.

## 3. Handler: re-read source quantity and forbid decomposition

- [x] 3.1 In `execute_modificar_producto`, when `resolved_data["cantidad"] is None`, re-read the current `PedidoProducto.cantidad` for the resolved source line inside the same transaction boundary, immediately before invoking the service, and pass the re-read value to `PedidoProductoService.modify_product` as the explicit quantity.
- [x] 3.2 Confirm the handler never substitutes `1` for an omitted quantity; the re-read is the only authoritative source.
- [x] 3.3 Confirm the handler never calls `execute_quitar_producto` or `execute_agregar_producto`; never manually decrements source; never manually creates destination.
- [x] 3.4 Confirm the handler returns exactly one `ProcessedIntent` per modification message; never a tuple, never a list, never a sequence of business outcomes.
- [x] 3.5 Confirm the handler never calls `db.commit()`, `db.rollback()`, `db.flush()`, or imports the response builder.
- [x] 3.6 Confirm exception propagation: `ModificationFailed` translates to `failed`; any other unexpected exception propagates unchanged so the transactional wrapper's `db.rollback()` is preserved.

## 4. Orchestration: omitted-quantity preservation across turns

- [x] 4.1 Confirm `process_initial_modificar_producto` never substitutes `1` for an omitted quantity when both domains are unique; the `cantidad is None` sentinel flows through unchanged.
- [x] 4.2 Confirm `process_initial_modificar_producto` never mutates the Pedido before the destination is ready; only the ready path delegates to the handler/service.
- [x] 4.3 Confirm `resolve_product_modification` persists the omitted-quantity sentinel (`cantidad is None`) across stages and never substitutes `1`; never mutates the Pedido while the destination is ambiguous.
- [x] 4.4 Confirm destination recognition failure (zero candidates, inactive, unavailable, foreign comercio, equivalent) returns `rejected` without calling the mutation service and without calling any source removal service.
- [x] 4.5 Confirm the orchestrator returns exactly one `ProcessedIntent` per modification message; the dispatch in `initial_intent_dispatcher` keeps the existing single-arm pattern for `modificar_producto`.

## 5. Response builder: extended deterministic matrix

- [x] 5.1 Update `_render_full_line` in `build_modificar_producto_response` to emit `Cambié <cantidad_modificada> <origen_nombre> por <cantidad_modificada> <destino_nombre>.` (the quantity appears explicitly on both sides).
- [x] 5.2 Update `_render_partial` to emit `Cambié <cantidad_modificada> <origen_nombre> por <cantidad_modificada> de <destino_nombre>. Quedan <cantidad_origen_restante> <origen_nombre>.`.
- [x] 5.3 Add the unknown-destination rendering: `No encontré el producto de reemplazo. Tu pedido no fue modificado.` triggered when the rejection reason is `destination_unavailable` and the destination product does not exist in the comercio catalog.
- [x] 5.4 Update the unavailable-destination rendering to `El producto de reemplazo no está disponible. Tu pedido no fue modificado.` so the customer sees an explicit Pedido-preserved confirmation.
- [x] 5.5 Update the excess-quantity rendering to `Solo tenés <cantidad_actual> <origen_nombre> para cambiar. Tu pedido no fue modificado.` so the customer sees an explicit Pedido-preserved confirmation.
- [x] 5.6 Confirm the response builder never invokes an LLM client, never constructs a prompt, and never exposes a database identifier in the rendered message.
- [x] 5.7 Confirm the response orchestrator invokes `build_modificar_producto_response` exactly once per `modificar_producto` outcome and never uses the generic fallback.

## 6. Focused tests for the corrected service and handler

- [x] 6.1 Add focused test asserting that `modify_product` performs every destination validation before mutating the source: stub the destination `ProductoPresentacion` to be unavailable after the source has been loaded and confirm the source row is unchanged.
- [x] 6.2 Add focused test asserting that `modify_product` returns `destination_unavailable` without mutating the source when the destination is unknown to the comercio catalog (the `caramelo` regression scenario).
- [x] 6.3 Add focused test asserting that `modify_product` returns `rejected` with `reason="destination_price_missing"` when the destination is new and no `Precio` row exists; the source row is unchanged.
- [x] 6.4 Add focused test asserting that `modify_product` computes `cantidad_a_modificar == 4` when `cantidad is None` and the source has `cantidad == 4`; the destination receives `cantidad == 4`.
- [x] 6.5 Add focused test asserting that `modify_product` never substitutes `1` for an omitted quantity.
- [x] 6.6 Add focused test asserting that `modify_product` reads `current_precio` strictly before any source mutation (assert via repository mock call order).
- [x] 6.7 Add focused test asserting that `execute_modificar_producto` re-reads the current `PedidoProducto.cantidad` when the resolved intent carries `cantidad is None`; the destination receives the re-read quantity.
- [x] 6.8 Add focused test asserting that `execute_modificar_producto` does not import `execute_quitar_producto` or `execute_agregar_producto`.
- [x] 6.9 Add focused test asserting that `execute_modificar_producto` returns exactly one `ProcessedIntent` for any branch.
- [x] 6.10 Add focused test asserting that `process_initial_modificar_producto` persists the omitted-quantity sentinel (`cantidad is None`) when both domains are unique.
- [x] 6.11 Add focused test asserting that `resolve_product_modification` persists the omitted-quantity sentinel across stages and never substitutes `1`.

## 7. End-to-end tests for the real defect matrix

- [x] 7.1 Add `test_omitted_quantity_transfers_full_source_quantity` to `test_modificar_producto_end_to_end.py`: seed `Empanada de Verdura x4`, send `cambia las empanadas de verdura por empanadas carne picante`, assert `Verdura` removed, `Carne Picante x4`, one `executed` `ProcessedIntent`, one customer response.
- [x] 7.2 Add `test_explicit_partial_quantity_decrements_source_creates_destination`: seed `Empanada de Verdura x4`, send `cambia 2 empanadas de verdura por empanadas carne picante`, assert `Verdura x2`, `Carne Picante x2`.
- [x] 7.3 Add `test_explicit_full_quantity_removes_source_creates_destination`: seed `Empanada de Verdura x4`, send `cambia las 4 empanadas de verdura por empanadas carne picante`, assert `Verdura` removed, `Carne Picante x4`.
- [x] 7.4 Add `test_unknown_destination_preserves_pedido`: seed `Empanada de Jamón y Queso x5`, send `cambia las 5 empanadas de jamon y queso por un caramelo`, assert `Jamón y Queso` remains `cantidad == 5`, no destination line created, no intermediate removal response, one rejection response confirming the Pedido is unchanged.
- [x] 7.5 Add `test_unavailable_destination_preserves_pedido`: seed a destination `ProductoPresentacion` and mark it inactive, send a modification that resolves to it, assert the source is unchanged and the response confirms the Pedido is unchanged.
- [x] 7.6 Add `test_ambiguous_destination_preserves_pedido`: seed two active destination candidates, send an ambiguous message, assert `pending_resolution` with `stage="destination_selection"`, source unchanged, source quantity preserved, `cantidad is None` persisted across turns.
- [x] 7.7 Add `test_destination_clarification_after_omitted_quantity`: seed `Empanada de Verdura x4`, send an ambiguous destination message omitting quantity, follow up with a clarification, assert the destination receives `cantidad == 4`.
- [x] 7.8 Add `test_destination_clarification_after_explicit_quantity`: seed `Empanada de Verdura x5`, send an ambiguous destination message with `cantidad == 2`, follow up with a clarification, assert the source remains `cantidad == 3` and the destination receives `cantidad == 2`.
- [x] 7.9 Add `test_destination_already_exists_increments_in_place`: seed source x4 and destination x2, send the modification, assert source removed, destination `cantidad == 6`, stored price preserved.
- [x] 7.10 Add `test_destination_equals_source_rejected`: seed source line, send a modification that resolves to the same `producto_presentacion_id`, assert `rejected` and source unchanged.
- [x] 7.11 Add `test_excess_quantity_rejected_with_pedido_preserved`: seed source `cantidad == 2`, send `cambia 5`, assert `rejected` with `reason="quantity_exceeds_source"`, source unchanged, destination unchanged.
- [x] 7.12 Add `test_missing_destination_price_rejected_without_mutation`: seed source line and a destination `ProductoPresentacion` without a `Precio` row, send the modification, assert the source is unchanged and the destination is unchanged.
- [x] 7.13 Add `test_technical_exception_before_mutation_propagates`: monkeypatch the destination load to raise `OperationalError` and assert the exception propagates; the transaction rolls back; the Pedido is unchanged.
- [x] 7.14 Add `test_technical_exception_during_mutation_propagates`: monkeypatch `decrement` to raise `IntegrityError` after the destination has been staged and assert the exception propagates; the outer transaction rolls back; source and destination are unchanged.
- [x] 7.15 Add `test_single_processed_intent_invariant`: assert `process_incoming_message` returns exactly one `ProcessedIntent` per `modificar_producto` message; never a list of `quitar_producto` plus `agregar_producto` outcomes.
- [x] 7.16 Add `test_single_customer_response_invariant`: assert the response orchestrator invokes `build_modificar_producto_response` exactly once per successful modification; the rendered message does not contain both `Quité` and `Agregué` substrings.

## 8. HTTP and CLI regressions

- [x] 8.1 Add `test_http_error1_regression` to the HTTP integration suite: drive `POST /comercios/{id}/clientes/{id}/incoming-messages` with the omitted-quantity scenario, assert the persisted Pedido ends as `Carne Picante x4` only.
- [x] 8.2 Add `test_http_error2_regression`: drive the HTTP endpoint with the unknown-destination scenario, assert the persisted Pedido ends as `Jamón y Queso x5` unchanged.
- [x] 8.3 Update `test_cli_chat_client.py` to assert the CLI table shows `Empanada de Carne Picante | Unidad | 4` after the Error 1 scenario and `Empanada de Jamón y Queso | Unidad | 5` after the Error 2 scenario.
- [x] 8.4 Re-run the existing `agregar_producto` end-to-end and intent-dispatcher tests against `supernova_test` to confirm no regression.
- [x] 8.5 Re-run the existing `quitar_producto` end-to-end and intent-dispatcher tests against `supernova_test` to confirm no regression.
- [x] 8.6 Re-run the existing CLI conversation regression test against the running local FastAPI app to confirm no regression.

## 9. Transactional and dispatcher regressions

- [x] 9.1 Add a regression asserting that `process_incoming_message_transactional` commits exactly once on a successful modification; no lower-level commit inside the service or handler.
- [x] 9.2 Add a regression asserting that a raised exception inside the modify path results in exactly one rollback from the transactional wrapper; no partial commit.
- [x] 9.3 Re-run the existing `initial_intent_dispatcher` test asserting that `modificar_producto` is dispatched only to `process_initial_modificar_producto` and never to the `agregar_producto` or `quitar_producto` orchestrators.
- [x] 9.4 Re-run the existing `pending_context_dispatcher` test asserting that `product_modification` is routed to `resolve_product_modification` and delegates `ready` to `execute_ready_pending_context`.
- [x] 9.5 Re-run the existing `pending_context_execution` test asserting that `handler == "modificar_producto"` is dispatched to `execute_modificar_producto` and that definitive `rejected` clears the pending context.

## 10. Manual CLI acceptance

- [x] 10.1 Scenario 1: add 4 Empanadas de Verdura, send `cambia las empanadas de verdura por empanadas carne picante`, assert one response for the modification, no separate remove/add responses, source removed, destination `cantidad == 4`.
- [x] 10.2 Scenario 2: add 5 Empanadas de Jamón y Queso, send `cambia las 5 empanadas de jamon y queso por un caramelo`, assert `rejected` response, `Jamón y Queso` remains `cantidad == 5`, Pedido is not empty, conversation continues normally.
- [x] 10.3 Scenario 3: add 5 Empanadas de Verdura, send `cambia 2 empanadas de verdura por carne picante`, assert `Verdura` `cantidad == 3`, `Carne Picante` `cantidad == 2`.

## 11. Verification and reporting

- [x] 11.1 `PYTHONPATH=. venv/bin/python -m compileall backend` exits 0.
- [x] 11.2 `openspec validate fix-modificar-producto-atomicity-quantity-3-32-1 --strict` reports valid.
- [x] 11.3 Report exact root causes, previous non-atomic execution path, corrected quantity derivation, corrected atomic service boundary, files changed, tests executed and results, manual CLI results, and confirmation that the change remains active and unsynchronized.
- [x] 11.4 Confirm the change remains under `openspec/changes/fix-modificar-producto-atomicity-quantity-3-32-1/` and that no main spec has been synchronized and no archival has occurred.
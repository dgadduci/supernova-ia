## 1. Static contract

- [x] 1.1 Add `backend/intents/contracts/modificar_producto.py` exporting `MODIFICAR_PRODUCTO_CONTRACT` with `intent="modificar_producto"`, `recognizer="modificar_producto_recognizer"`, `handler="modificar_producto"`, and `requirements` for `pedido_producto_origen_id` (required), `producto_presentacion_destino_id` (required), and `cantidad` (optional, default `None`)
- [x] 1.2 Register `MODIFICAR_PRODUCTO_CONTRACT` in the contract registry alongside `AGREGAR_PRODUCTO_CONTRACT` and `QUITAR_PRODUCTO_CONTRACT`
- [x] 1.3 Ensure the contract module exports only `MODIFICAR_PRODUCTO_CONTRACT` through `__all__`

## 2. Repository and service surface for PedidoProducto

- [x] 2.1 Add `PedidoProductoRepository.get_for_pedido(db, pedido_id, pedido_producto_id)` returning the matching `PedidoProducto` or `None`
- [x] 2.2 Add `PedidoProductoRepository.decrement(db, pedido_producto_id, cantidad)` decrementing the row's quantity in place and returning the updated row
- [x] 2.3 Reuse existing `PedidoProductoRepository.delete` for full-line deletion
- [x] 2.4 Add `PedidoProductoRepository.increment(db, pedido_producto_id, cantidad)` incrementing the row's quantity in place and returning the updated row
- [x] 2.5 Add `PedidoProductoRepository.create_with_price_snapshot(db, pedido_id, producto_presentacion_id, cantidad, precio_unitario)` creating exactly one new row with the supplied price snapshot
- [x] 2.6 Add `PedidoProductoService.modify_product(db, pedido_id, pedido_producto_origen_id, producto_presentacion_destino_id, cantidad)` performing all pre-mutation validations (Pedido borrador, ownership, source validity, destination validity, quantity semantics, equivalent-modification guard), the atomic mutation, and the `ModificationResult`
- [x] 2.7 Verify `PedidoProductoService.list_by_pedido` continues to load order lines eagerly with `producto_presentacion.producto` so the handler can resolve display names without N+1
- [x] 2.8 Confirm the existing `add_or_increment` (destination consolidation) and the borrador-only guard remain intact

## 3. Recognizer

- [x] 3.1 Add `backend/intents/recognizers/modificar_producto_recognizer.py` exposing `recognize_modificar_producto(db, session, message) -> RecognizerResult`
- [x] 3.2 Build the source candidate catalog exclusively from `PedidoProductoService.list_by_pedido(session.id_pedido)`; never query the commerce catalog for source resolution
- [x] 3.3 Build the destination candidate catalog exclusively from the active and available `ProductoPresentacion` rows of the comercio through the existing product-query service
- [x] 3.4 Emit `source_candidate_ids` and `destination_candidate_ids` as distinct fields; never combine the two identifier domains into one list
- [x] 3.5 Extract an explicit positive integer quantity when present; default to `None` when the message omits a quantity
- [x] 3.6 Ensure inactive or unavailable catalog products never appear as destination candidates
- [x] 3.7 Ensure catalog products absent from the draft Pedido never appear as source candidates
- [x] 3.8 Export only `recognize_modificar_producto` through `__all__`

## 4. Initial intent orchestration

- [x] 4.1 Add `backend/intents/orchestration/modificar_producto_initial.py` exposing `process_initial_modificar_producto(db, session, source_text) -> ProcessedIntent`
- [x] 4.2 Return `rejected` when `session.id_pedido is None`, without mutating any state
- [x] 4.3 Load the active draft pedido and current order lines through existing services; never run SQLAlchemy queries directly
- [x] 4.4 Load the active and available destination catalog through the existing product-query service
- [x] 4.5 Return `ready` with `pedido_producto_origen_id`, `producto_presentacion_destino_id`, and preserved `cantidad` when both domains resolve uniquely and are not equivalent
- [x] 4.6 Return `pending_resolution` with `context_type="product_modification"`, `stage="source_selection"`, and distinct `source_candidate_ids` / `destination_candidate_ids` when the source is ambiguous
- [x] 4.7 Return `pending_resolution` with `stage="destination_selection"`, the unique resolved source ID, and the remaining `destination_candidate_ids` when only the destination is ambiguous
- [x] 4.8 Return `rejected` (no pending context) when the recognizer returns zero source candidates, zero destination candidates, the destination is inactive or unavailable, or the source equals the destination
- [x] 4.9 Export only `process_initial_modificar_producto` through `__all__`

## 5. Context type and resolver

- [x] 5.1 Add `ContextType.PRODUCT_MODIFICATION` to `SESSION_CONTEXT_TYPE` with the distinct string value `"product_modification"`
- [x] 5.2 Update `ContextTypeResolver.resolve_context_type` so a ready `modificar_producto` intent returns `PRODUCT_MODIFICATION`, while `agregar_producto` and `quitar_producto` continue to return `PRODUCT_SELECTION` and `ORDER_LINE_SELECTION` respectively
- [x] 5.3 Add `backend/intents/context/product_modification_resolver.py` exposing `resolve_product_modification(db, session, message, active_intent) -> ProcessedIntent`
- [x] 5.4 Restrict refinement to the current `source_candidate_ids` and `destination_candidate_ids`; never broaden either domain back to the full Pedido or full catalog
- [x] 5.5 When refinement narrows the source candidates to exactly one, transition to `stage="destination_selection"` if the destination is still ambiguous, otherwise populate `resolved_data["pedido_producto_origen_id"]` and `resolved_data["producto_presentacion_destino_id"]` and return `ready`
- [x] 5.6 When refinement narrows the destination candidates to exactly one and the source is already unique, return `ready` with the preserved source ID, the resolved destination ID, and the preserved `cantidad`
- [x] 5.7 Preserve the resolved source ID, the optional `cantidad`, and the previously resolved destination data across refinement turns
- [x] 5.8 When the message resolves to a source ID outside `source_candidate_ids` or a destination ID outside `destination_candidate_ids`, return `rejected` without mutating the Pedido and without broadening the candidate set
- [x] 5.9 Export only `resolve_product_modification` through `__all__`

## 6. Handler

- [x] 6.1 Add `backend/intents/handlers/modificar_producto_handler.py` exposing `execute_modificar_producto(db, session, intent) -> ProcessedIntent`
- [x] 6.2 Validate `intent.intent == "modificar_producto"`, `intent.status == "ready"`, `intent.handler == "modificar_producto"`, and the presence of `resolved_data["pedido_producto_origen_id"]` and `resolved_data["producto_presentacion_destino_id"]`
- [x] 6.3 Validate `pedido_producto_origen_id` and `producto_presentacion_destino_id` are integers; validate `cantidad` is a positive integer when present; reject otherwise
- [x] 6.4 Require `session.id_pedido`; reject when missing; delegate to `PedidoProductoService.modify_product` for every other check
- [x] 6.5 Never issue SQLAlchemy queries directly; never perform source decrement and destination increment manually
- [x] 6.6 On success, return `executed` with `resolved_data` enriched with `producto_origen_nombre`, `presentacion_origen`, `producto_destino_nombre`, `presentacion_destino`, `cantidad_modificada`, `cantidad_origen_restante`, `cantidad_destino_final`, `origen_eliminado`, `destino_creado`
- [x] 6.7 Translate business-rule failures (quantity exceeds source, source not in pedido, destination unavailable, foreign comercio, equivalent modification, pedido not editable) to `rejected` with deterministic reason codes
- [x] 6.8 Translate unexpected technical exceptions to `failed` only when the service raises a `ModificationFailed` sentinel; propagate any other exception unchanged so the transactional wrapper's `db.rollback()` is preserved
- [x] 6.9 Never commit, rollback, flush, close, or generate responses
- [x] 6.10 Export only `execute_modificar_producto` through `__all__`

## 7. Response builder

- [x] 7.1 Add `backend/intents/responses/modificar_producto_response.py` exposing `build_modificar_producto_response(db, session, intent) -> CustomerResponse`
- [x] 7.2 Implement `pending_resolution` source rendering `¿Cuál producto querés cambiar: <a> o <b>( o <c>)?` from formatted `producto_nombre (presentacion_codigo)` pairs resolved through `PedidoProductoService.list_by_pedido`
- [x] 7.3 Implement `pending_resolution` destination rendering `¿Cuál querés como reemplazo: <a>, <b> o <c>?` from formatted `producto_nombre (presentacion_codigo)` pairs resolved through the existing product-query service
- [x] 7.4 Implement `executed` full-line swap rendering `Cambié <origen_nombre> (<origen_presentacion>) por <destino_nombre> (<destino_presentacion>).`
- [x] 7.5 Implement `executed` partial rendering `Cambié <cantidad_modificada> <origen_nombre> (<origen_presentacion>) por <cantidad_modificada> de <destino_nombre> (<destino_presentacion>). Quedan <cantidad_origen_restante> <origen_nombre> (<origen_presentacion>).`
- [x] 7.6 Implement `executed` consolidated rendering `Cambié <cantidad_origen> <origen_nombre> (<origen_presentacion>) por <destino_nombre> (<destino_presentacion>). Ahora tenés <cantidad_destino_final> <destino_nombre> (<destino_presentacion>).`
- [x] 7.7 Implement `rejected` excess rendering `Solo tenés <cantidad_actual> <origen_nombre> (<origen_presentacion>) para cambiar.`
- [x] 7.8 Implement `rejected` source absent rendering `Ese producto no está en tu pedido.`
- [x] 7.9 Implement `rejected` destination unavailable rendering `Ese producto no está disponible como reemplazo.`
- [x] 7.10 Implement `rejected` equivalent modification rendering `Ese producto ya tiene esa presentación en tu pedido.`
- [x] 7.11 Implement `failed` rendering the generic retry message without technical detail
- [x] 7.12 Ensure `CustomerResponse.intent == "modificar_producto"` and `CustomerResponse.status == intent.status` for every outcome
- [x] 7.13 Forbid any LLM call, prompt construction, or technical detail in the message
- [x] 7.14 Export only `build_modificar_producto_response` through `__all__`

## 8. Integration seams

- [x] 8.1 Update `backend/intents/orchestration/initial_intent_dispatcher.py` to dispatch `modificar_producto` to `process_initial_modificar_producto`, preserving `ready`, `pending_resolution`, `rejected`, and `failed` outcomes unchanged and never invoking the other orchestrators
- [x] 8.2 Update `backend/intents/orchestration/pending_context_dispatcher.py` to route `session.context_type == "product_modification"` to `resolve_product_modification`, persist the active intent through `set_active`, and delegate `ready` to `execute_ready_pending_context`
- [x] 8.3 Update `backend/intents/orchestration/pending_context_execution.py` to dispatch `handler == "modificar_producto"` to `execute_modificar_producto` while keeping the existing `agregar_producto` and `quitar_producto` arms and the rejection-clears-context rule
- [x] 8.4 Update `backend/intents/orchestration/incoming_message_response_orchestrator.py` to delegate `modificar_producto` outcomes to `build_modificar_producto_response` instead of the generic fallback
- [x] 8.5 Confirm `agregar_producto` and `quitar_producto` regressions are preserved across all four seams (initial dispatcher, pending-context dispatcher, pending-context execution, response orchestrator)

## 9. Tests

- [x] 9.1 Add focused tests for `MODIFICAR_PRODUCTO_CONTRACT` (top-level shape, requirements, optional `cantidad`, forbidden LLM-provided DB fields, registry inclusion)
- [x] 9.2 Add focused tests for `recognize_modificar_producto` (source limited to draft pedido, destination limited to active catalog, quantity extraction, zero/negative quantity rejected, distinct candidate domains)
- [x] 9.3 Add focused tests for `process_initial_modificar_producto` (unique ready, ambiguous source pending, ambiguous destination pending, both ambiguous, no source rejected, missing pedido rejected, equivalent modification rejected, inactive destination rejected, quantity preserved)
- [x] 9.4 Add focused tests for `resolve_product_modification` (source refinement narrows, source unique advances to destination, destination refinement narrows, invalid source rejected, invalid destination rejected, no broadening, preserved cantidad, preserved source ID)
- [x] 9.5 Add focused tests for `execute_modificar_producto` (delegation to service, intent validation, executed enrichment, rejected translations, exception propagation, no commit/rollback, no SQLAlchemy access)
- [x] 9.6 Add focused tests for `build_modificar_producto_response` (every documented message template, intent/status preserved, no LLM imports, no DB ID exposure)
- [x] 9.7 Add focused tests for `PedidoProductoService.modify_product` (full pre-mutation validations, quantity semantics, equivalent-modification guard, consolidation invariant, price-snapshot rules, atomic transactional boundary, no commit/rollback)
- [x] 9.8 Add focused tests for the new `PedidoProductoRepository` methods (DB-only, expected return values, no business logic)
- [x] 9.9 Add focused tests for `initial_intent_dispatcher` dispatching `modificar_producto` (calls only `process_initial_modificar_producto`, never the other orchestrators, preserves status)
- [x] 9.10 Add focused tests for `pending_context_dispatcher` routing `product_modification` (persists reduced candidates, distinct domains preserved, delegates `ready` to `execute_ready_pending_context`)
- [x] 9.11 Add focused tests for `pending_context_execution` dispatching `modificar_producto` (executes when ready, clears context on executed, clears context on definitive rejected, preserves on failed, propagates exceptions)
- [x] 9.12 Add focused tests for `incoming_message_response_orchestrator` delegating `modificar_producto` to `build_modificar_producto_response` (each status route, no invocation of other builders)
- [x] 9.13 Add the end-to-end integration test for `modificar_producto` covering happy path (full-line swap, partial modification, omitted cantidad), excess-quantity rejection, source-absent rejection, destination-unavailable rejection, equivalent-modification rejection, consolidated-destination increment, new-destination creation, source ambiguity, destination ambiguity, both ambiguous (resolution order source → destination), partial refinement, invalid source candidate rejection, invalid destination candidate rejection, definitive handler rejection (clears context), and the consecutive mixed-operation scenario (add → modify → modify → remove → add)
- [x] 9.14 Re-run the existing `agregar_producto` end-to-end and intent-dispatcher tests against `supernova_test` to confirm no regression
- [x] 9.15 Re-run the existing `quitar_producto` end-to-end and intent-dispatcher tests against `supernova_test` to confirm no regression
- [x] 9.16 Re-run the existing CLI conversation regression test against the running local FastAPI app to confirm the CLI drives `modificar_producto` flows without code changes and the current-order table renders correctly after an executed modification

## 10. Verification

- [x] 10.1 `PYTHONPATH=. venv/bin/python -m compileall backend` exits 0
- [x] 10.2 `openspec validate modificar-producto-end-to-end-3-32 --strict` reports valid
- [x] 10.3 Report manual CLI acceptance scenarios separately from automated tests (full-line modification, partial modification, omitted cantidad, source ambiguity, destination ambiguity, consolidated destination, excess quantity, unavailable destination, equivalent modification, regression after each rejection)

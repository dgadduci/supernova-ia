## 1. Static contract

- [x] 1.1 Add `backend/intents/contracts/quitar_producto.py` exporting `QUITAR_PRODUCTO_CONTRACT` with `intent`, `recognizer`, `handler`, and `requirements` for `pedido_producto_id` (required, default `None`) and `cantidad` (optional, default `None`)
- [x] 1.2 Ensure the contract module exports only `QUITAR_PRODUCTO_CONTRACT` through `__all__`

## 2. Repository and service surface for PedidoProducto

- [x] 2.1 Add `PedidoProductoRepository.list_by_pedido(db, pedido_id)` returning a list of `PedidoProducto` eagerly loaded with `producto_presentacion.producto` so handlers can resolve display names without N+1
- [x] 2.2 Add `PedidoProductoRepository.get_for_pedido(db, pedido_id, pedido_producto_id)` returning the matching `PedidoProducto` or `None`
- [x] 2.3 Add `PedidoProductoService.list_by_pedido(db, pedido_id)` delegating to the repository and returning the same list (no extra filtering)
- [x] 2.4 Add `PedidoProductoService.get_for_pedido(db, pedido_id, pedido_producto_id)` delegating to the repository and raising `PedidoProductoNotFound` when the line is absent or belongs to another pedido
- [x] 2.5 Verify the existing `PedidoProductoService.update` (cantidad/observaciones) and `delete` continue to enforce the borrador-only guard and return the documented exceptions

## 3. Recognizer

- [x] 3.1 Add `backend/intents/recognizers/quitar_producto_recognizer.py` exposing `recognize_quitar_producto(db, session, message) -> RecognizerResult`
- [x] 3.2 Build the candidate catalog exclusively from `PedidoProductoService.list_by_pedido(session.id_pedido)`; never query the commerce catalog
- [x] 3.3 Extract an explicit positive integer quantity when present; default to `None` when the message omits a quantity
- [x] 3.4 Ensure inactive or unavailable catalog products that already exist in the pedido remain reachable as candidates

## 4. Initial intent orchestration

- [x] 4.1 Add `backend/intents/orchestration/quitar_producto_initial.py` exposing `process_initial_quitar_producto(db, session, source_text) -> ProcessedIntent`
- [x] 4.2 Return `rejected` when `session.id_pedido` is `None`, without mutating any state
- [x] 4.3 Load the active draft pedido through existing services and `list_by_pedido`; never run SQLAlchemy queries directly
- [x] 4.4 Return `ready` (with `pedido_producto_id` populated) when the recognizer returns exactly one candidate; preserve the optional `cantidad`
- [x] 4.5 Return `pending_resolution` (with `context_type="order_line_selection"` and `candidate_ids` listing the candidate `pedido_producto_id` values) when the recognizer returns more than one candidate
- [x] 4.6 Return `rejected` (no pending context) when the recognizer returns zero candidates or the draft pedido has zero lines
- [x] 4.7 Export only `process_initial_quitar_producto` through `__all__`

## 5. Context type and resolver

- [x] 5.1 Add `ContextType.ORDER_LINE_SELECTION` to `SESSION_CONTEXT_TYPE` with a distinct string value (e.g. `"order_line_selection"`)
- [x] 5.2 Update `ContextTypeResolver.resolve_context_type` so a ready `quitar_producto` intent returns `ORDER_LINE_SELECTION` and a ready `agregar_producto` intent still returns `PRODUCT_SELECTION`
- [x] 5.3 Add `backend/intents/context/order_line_selection_resolver.py` exposing `resolve_order_line_selection(db, session, message, active_intent) -> ProcessedIntent`
- [x] 5.4 Restrict refinement to the current `candidate_ids`; never broaden back to the commerce catalog
- [x] 5.5 When refinement narrows to exactly one candidate, populate `resolved_data["pedido_producto_id"]`, set `status="ready"`, and let the existing ready-execution path dispatch the handler
- [x] 5.6 When refinement yields several candidates, set `status="pending_resolution"` with the reduced `candidate_ids`
- [x] 5.7 When the message resolves to a `pedido_producto_id` not in the current candidate set, return `rejected` without mutating the pedido
- [x] 5.8 Export only `resolve_order_line_selection` through `__all__`

## 6. Handler

- [x] 6.1 Add `backend/intents/handlers/quitar_producto_handler.py` exposing `execute_quitar_producto(db, session, intent) -> ProcessedIntent`
- [x] 6.2 Validate `intent.intent == "quitar_producto"`, `intent.status == "ready"`, `intent.handler == "quitar_producto"`, and presence of `resolved_data["pedido_producto_id"]`
- [x] 6.3 Validate `pedido_producto_id` is an integer; validate `cantidad` is a positive integer when present; reject otherwise
- [x] 6.4 Require `session.id_pedido`; reject when missing; verify ownership through `PedidoProductoService.get_for_pedido` and reject when the line belongs to a different pedido
- [x] 6.5 When `cantidad` is omitted, call `PedidoProductoService.delete(pedido_producto_id)`
- [x] 6.6 When `cantidad` equals the current line quantity, call `PedidoProductoService.delete(pedido_producto_id)`
- [x] 6.7 When `cantidad` is less than the current line quantity, call `PedidoProductoService.update(pedido_producto_id, cantidad=current - cantidad)`
- [x] 6.8 When `cantidad` exceeds the current line quantity, return `rejected` with `resolved_data["cantidad_actual"]` populated and do not mutate the order
- [x] 6.9 On success, return `executed` with `resolved_data` enriched with `producto_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `cantidad_removida`, `cantidad_restante`, and `linea_eliminada`
- [x] 6.10 Translate business-rule failures to `rejected`; unexpected technical failures to `failed`; never raise `HTTPException`; never catch broad `Exception`
- [x] 6.11 Never commit, rollback, flush, close, or generate responses
- [x] 6.12 Export only `execute_quitar_producto` through `__all__`

## 7. Response builder

- [x] 7.1 Add `backend/intents/responses/quitar_producto_response.py` exposing `build_quitar_producto_response(db, session, intent) -> CustomerResponse`
- [x] 7.2 Implement `pending_resolution` rendering `¿Cuál querés quitar: <a> o <b>( o <c>)?` from formatted `producto_nombre (presentacion_codigo)` pairs resolved through `PedidoProductoService.list_by_pedido`
- [x] 7.3 Implement `executed` partial rendering `Quité {cantidad_removida} {producto_nombre} ({presentacion_codigo}). Queda {cantidad_restante} en tu pedido.`
- [x] 7.4 Implement `executed` complete rendering `Quité {producto_nombre} ({presentacion_codigo}) de tu pedido.`
- [x] 7.5 Implement `rejected` excess rendering `Solo tenés {cantidad_actual} {producto_nombre} ({presentacion_codigo}) en el pedido.`
- [x] 7.6 Implement `rejected` absent rendering `Ese producto no está en tu pedido.`
- [x] 7.7 Implement `failed` rendering `No pude procesar tu pedido. Intentá de nuevo en un momento.`
- [x] 7.8 Ensure `CustomerResponse.intent == "quitar_producto"` and `CustomerResponse.status == intent.status` for every outcome
- [x] 7.9 Forbid any LLM call, prompt construction, or technical detail in the message
- [x] 7.10 Export only `build_quitar_producto_response` through `__all__`

## 8. Integration seams

- [x] 8.1 Update `backend/intents/orchestration/initial_intent_dispatcher.py` to dispatch `quitar_producto` to `process_initial_quitar_producto`, preserving `ready`, `pending_resolution`, and `rejected` outcomes unchanged
- [x] 8.2 Update `backend/intents/orchestration/pending_context_dispatcher.py` to route `session.context_type == "order_line_selection"` to `resolve_order_line_selection`, persist the active intent through `set_active`, and delegate `ready` to `execute_ready_pending_context`
- [x] 8.3 Update `backend/intents/orchestration/pending_context_execution.py` to dispatch `handler == "quitar_producto"` to `execute_quitar_producto` while keeping the existing `agregar_producto` arm and the rejection-clears-context rule
- [x] 8.4 Update `backend/intents/orchestration/incoming_message_response_orchestrator.py` to delegate `quitar_producto` outcomes to `build_quitar_producto_response` instead of the generic fallback
- [x] 8.5 Confirm `agregar_producto` regression is preserved across all four seams

## 9. Tests

- [x] 9.1 Add focused tests for `QUITAR_PRODUCTO_CONTRACT` (top-level shape, requirements, forbidden fields)
- [x] 9.2 Add focused tests for `recognize_quitar_producto` (catalog limited to draft pedido, quantity extraction, no catalog fallback, inactive catalog products reachable)
- [x] 9.3 Add focused tests for `process_initial_quitar_producto` (unique ready, ambiguous pending, no match rejected, missing pedido rejected)
- [x] 9.4 Add focused tests for `resolve_order_line_selection` (refinement narrows, single candidate returns ready, invalid candidate rejected, no broadening)
- [x] 9.5 Add focused tests for `execute_quitar_producto` (decrement, exact delete, omit delete, excess rejected, missing pedido rejected, wrong ownership rejected, invalid resolved values rejected)
- [x] 9.6 Add focused tests for `build_quitar_producto_response` (each outcome string, no LLM imports, intent and status preserved)
- [x] 9.7 Add focused tests for `PedidoProductoRepository` and `PedidoProductoService` new methods
- [x] 9.8 Add the end-to-end integration test for `quitar_producto` covering pending → refinement → executed removal, partial decrement, excess rejection, absent-product rejection, and the consecutive mixed-operation scenario
- [x] 9.9 Re-run the existing `agregar_producto` end-to-end and intent-dispatcher tests against `supernova_test` to confirm no regression
- [x] 9.10 Re-run the existing CLI conversation regression test against the running local FastAPI app to confirm the CLI drives `quitar_producto` flows without code changes

## 10. Verification

- [x] 10.1 `PYTHONPATH=. venv/bin/python -m compileall backend` exits 0
- [x] 10.2 `openspec validate subphase-3-31-quitar-producto --strict` reports valid
- [x] 10.3 Report manual CLI acceptance scenarios separately from automated tests (single-message complete removal, partial decrement, excess rejection, ambiguous refinement, absent product, regression)

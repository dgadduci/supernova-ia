## Why

The product-selection narrowing branch in `ProductSelectionContextResolver` matches the presentacion alias only against the `presentacion_codigo` column. When the discriminating fragment in the user's reply lives in the product name instead of the presentation code (e.g. `picante`, `tradicional`), the narrow step finds zero matches and falls through, so the customer is asked to clarify again instead of being auto-selected. This blocks the same flows the 3.32.5 extraneous-guard fix unlocked — the message passes the guard but still fails to narrow.

## What Changes

- Extend `_narrow_by_presentacion_alias` in `backend/intents/context/product_selection_context_resolver.py` to also match the presentacion alias token against each candidate's `producto_nombre` (case-insensitive whole-word match), so aliases stored in `PRESENTACION_ALIASES` that discriminate at the product level (e.g. `picante`, `tradicional`) can narrow the candidate list.
- Keep the existing `presentacion_codigo` match path intact; the new branch is additive and only widens the matching set.
- Preserve all existing behavior: status transitions, quantity preservation, resolved-data preservation, FIFO queue promotion, no duplicate calls, diagnostic emissions unchanged.
- No new alias entries, no new prompt, no change to `detectar_productos`, no change to the threshold/tuning knobs, no change to the 3.32.4 drain-and-promote loop.

## Capabilities

### New Capabilities

- *(none)*

### Modified Capabilities

- `product-selection-context-resolver`: add a requirement that the presentacion-alias narrow step also matches the alias against each candidate's `producto_nombre` (whole-word, case-insensitive) so product-level aliases such as `picante` and `tradicional` can resolve the candidate set to a unique entry.
- `product-recognizer`: no requirement changes; the alias table and the `_extraer_presentacion` helper are reused as-is.

## Impact

- Modified files: `backend/intents/context/product_selection_context_resolver.py` (the loop in `_narrow_by_presentacion_alias` at lines 107-111 gains an additional match predicate), `backend/tests/test_product_selection_context_resolver.py` (new focused tests covering product-narrowing when the alias lives in `producto_nombre`, plus a regression that the presentacion_codigo path still narrows when applicable), and `backend/tests/test_agregar_producto_sequential_queue_end_to_end.py` (add a turn-2 `carne picante` case that asserts the resolver selects candidate id 32 in one pass).
- Reused unchanged: `PRESENTACION_ALIASES` table, `_extraer_presentacion`, `detectar_productos`, the `_extraneous_words_relate_to_active_intent` guard from 3.32.5, the 3.32.4 drain-and-promote loop, the diagnostic sink surface from 3.32.6, the HTTP contracts, the customer-facing response logic, the `ProcessedIntent` schema, the `PendingIntents` FIFO queue, the `PedidoDetalleResponse` endpoint.
- Not touched: CLI (`backend/scripts/cli_chat_client.py`), the FastAPI router, the orchestrator, the classifier, the pending-context dispatcher, the `modificar_producto` path, the `quitar_producto` path, any database column, any prompt, any threshold, any transaction ownership, any new endpoint, any new dependency.
- Diagnostic surface: the fix is observable through the existing 3.32.6 `RESOLVER INPUT` / `RESOLVER OUTPUT` / `RESOLVER CANDIDATES` tables; no new diagnostic fields are required.

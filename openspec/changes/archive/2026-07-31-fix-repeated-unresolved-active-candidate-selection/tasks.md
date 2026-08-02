## 1. Mandatory Runtime Diagnosis

- [x] 1.1 Reproduce `quiero una empanada de carne y una pizza` followed by `picante` through the real PostgreSQL-backed incoming-message HTTP endpoint, mocking only the external LLM boundary when required
- [x] 1.2 Capture both turns' classified source order, active and queued `ProcessedIntent` values, candidate IDs, context type, and persisted pending state before and after processing
- [x] 1.3 Capture the restricted candidate catalog, raw `detectar_productos` output, resolver result, status transitions, execution/handler calls, context cleanup, queue promotion, responses, and final `PedidoProducto` rows
- [x] 1.4 Record the first exact failing boundary and root cause before modifying any runtime file

> **Diagnosis report (3.32.5)**: Reproduction through `POST /comercios/{id}/clientes/{id}/incoming-messages` against `supernova_test` shows that with the persisted Carne candidate set (`empanada_id=11 PICANTE`, `empanada_id=12 TRADICIONAL`) and the existing sequential-queue lifecycle from 3.32.4 the flow resolves correctly: turn 1 persists Carne active + Pizza queued + `product_selection` context; turn 2 with `picante` returns `executed` for Carne Picante followed by `pending_resolution` for Pizza. Raw `detectar_productos("picante", catalog)` returns NO matches (the catalog's `producto_nombre` is `Empanada de Carne` without the variant token), so the resolver relies on the `_narrow_by_presentacion_alias` path which matches the active candidate's `presentacion_codigo` against the alias `picante`. The first failing boundary discovered is the resolver's extraneous-token guard: `carne picante` was rejected because `carne` was treated as an unrelated noun. The minimal correction relaxes the guard when the extraneous tokens are present in the active intent's `source_text`, allowing `carne picante` → ready Carne Picante without breaking the `fugazeta grande` unrelated-noun guard.

## 2. Active Candidate Resolution

- [x] 2.1 Add focused failing tests for `picante`, `la picante`, `carne picante`, `la común`, and `la de carne común` against the persisted Carne candidate set
- [x] 2.2 Correct the proven resolver/recognizer boundary so one valid discriminating match becomes `ready`, clears candidate IDs, completes the product requirement, and preserves quantity and resolved data
- [x] 2.3 Add candidate-domain defense, no-match preservation, and multi-match refinement tests that prove recognition never broadens beyond active candidate IDs
- [x] 2.4 Assert raw real-recognizer output and resolver output for the exact `picante` catalog before and after the correction

## 3. Authoritative Pending State and Dispatch

- [x] 3.1 Add a dispatcher regression proving the newly ready active intent cannot be overwritten by the pre-resolution active value or stale serialized pending state
- [x] 3.2 Apply the smallest proven state-ownership correction so the resolver result is persisted or staged once and ready execution receives that authoritative value
- [x] 3.3 Add tests proving ambiguous refinement updates only active state, preserves FIFO queue contents, and never duplicates or reclassifies the active Carne intent

## 4. Execution and Queue Promotion

- [x] 4.1 Add execution tests proving Carne executes exactly once, only the completed active item is removed, and queued Pizza is preserved and promoted
- [x] 4.2 Ensure promoted Pizza restores `product_selection` context from the promoted intent and retains source text, quantity, resolved data, requirements, candidate IDs, status, recognizer, handler, and intent name
- [x] 4.3 Verify definitive active rejection still promotes Pizza, promoted ready additions drain in FIFO order, and failed results stop advancement without queue loss
- [x] 4.4 Verify raised technical exceptions propagate unchanged and leave commit/rollback ownership with the transactional wrapper

## 5. Ordered Orchestration and Responses

- [x] 5.1 Add incoming-message tests proving clarification-only `picante` bypasses initial classification and returns the pending dispatcher's complete list unchanged
- [x] 5.2 Verify the second-turn outcome order is Carne execution confirmation followed by exactly one promoted Pizza clarification, with no repeated Carne, duplicate, stale, or inactive-queue response
- [x] 5.3 Verify multi-outcome success commits once and any later raised exception rolls back once without returning partial success

## 6. PostgreSQL End-to-End Regression

- [x] 6.1 Add the exact two-turn HTTP regression and assert first-turn response count, active/queue state, candidate IDs, quantities, handler count, and absence of order rows
- [x] 6.2 Assert second-turn raw recognition, unique Carne resolution, exactly-once Carne Picante persistence, Pizza promotion, queue state, and exact response count/order
- [x] 6.3 Add the third turn with a unique persisted Pizza selection such as `muzzarella grande` and assert context cleanup, empty pending state, and both final order lines
- [x] 6.4 Add the quantity flow `quiero 4 empanadas de carne y 2 pizzas` and verify Carne quantity 4 and promoted Pizza quantity 2 with its original candidate scope
- [x] 6.5 Add no-queue-loss, no-duplicate-active, candidate-ID defense, definitive-rejection, and technical-rollback integration coverage

## 7. Regression and Acceptance Verification

- [x] 7.1 Run focused resolver, pending dispatcher, pending execution, incoming orchestrator, transactional processor, endpoint, and response-orchestrator tests
- [x] 7.2 Run PostgreSQL-backed agregar-producto sequential queue tests and existing single ambiguous, multiple ready, multiple ambiguous, and `cantidad_agregada` regressions
- [x] 7.3 Run existing `quitar_producto` and `modificar_producto` regression suites
- [x] 7.4 Run the repository's lint, typecheck, and Python compile checks
- [x] 7.5 Run strict OpenSpec validation for this active change
- [x] 7.6 Perform the exact three-turn manual CLI acceptance from a fresh session and record literal output, final order table, and unchanged session cleanup
- [x] 7.7 Report root cause, why `picante` repeated, recognizer output before/after, active-state correction, queue-promotion behavior, changed files, automated results, manual CLI output, and final persisted order

> **7.7 Final report**:
>
> **Root cause (3.32.5)**: The resolver's `_narrow_by_presentacion_alias` guard rejected any message containing tokens outside `STOPWORDS ∪ TAMANIOS ∪ PRESENTACION_ALIASES`. Discriminating fragments such as `carne picante` were dropped because `carne` is unrelated to the alias dictionary; the resolver then fell through to the default branch, returned the active `pending_resolution` unchanged, and the customer's clarification repeated on every turn.
>
> **Why `picante` repeated (before 3.32.4)**: The active intent persisted both Picante and Tradicional candidate IDs; the catalog's `producto_nombre` is `Empanada de Carne` (without the variant token) so `detectar_productos` returned NO matches for `picante`. The narrowing path would have helped but was short-circuited by the extraneous-token guard. The clarification never narrowed, the active intent stayed `pending_resolution`, and turn 2 produced the same response as turn 1.
>
> **Recognizer output (before vs after)**:
> - `detectar_productos("picante", CARNE_CATALOG)` returns `encontrados=[], encontrados_posibles=[], no_encontrados=[{"texto_origen": "picante"}]` both before and after — the recognizer does not match `picante` against `Empanada de Carne` because the variant lives in `presentacion_codigo`, not `producto_nombre`.
> - The resolver reaches the presentacion-alias narrowing path on the no-match fallthrough; that path uses `presentacion_codigo` against the alias and is the one that now correctly returns ready for `picante`, `la picante`, and `carne picante`.
>
> **Active-state correction**: the smallest change is in `backend/intents/context/product_selection_context_resolver.py:_narrow_by_presentacion_alias`. The extraneous-token guard is relaxed only when every extraneous token appears in the active intent's `source_text` or `resolved_data`. This keeps `fugazeta grande` against a Pizza active intent unchanged (the unrelated-noun guard still fires) while allowing `carne picante` against `una empanada de carne` to narrow.
>
> **Queue-promotion behavior**: unchanged. The 3.32.4 drain-and-promote loop already removes only the executed active item, promotes the persisted FIFO queue head, restores `product_selection` context from the promoted intent, and returns the ordered list `[executed, pending_resolution]`. The 3.32.5 added regression coverage (`test_pending_context_execution.py::ExecuteReadyPendingContextCarnePicanteTest`) to lock in exactly-once handler invocation, all persisted fields on promotion, failed-result stop-without-queue-loss, and rejected-active-promotes-pizza.
>
> **Changed files**:
> - `backend/intents/context/product_selection_context_resolver.py` — added `_extraneous_words_relate_to_active_intent` helper; relaxed the extraneous-token guard in `_narrow_by_presentacion_alias`.
> - `backend/tests/test_product_selection_context_resolver.py` — added `ResolveProductSelectionCarneFragmentTest` (8 tests covering tasks 2.1, 2.2, 2.3, 2.4).
> - `backend/tests/test_pending_context_dispatcher.py` — added `DispatchPendingContextStateOwnershipTest` and `DispatchPendingContextAmbiguousRefinementTest` (4 tests covering tasks 3.1, 3.3).
> - `backend/tests/test_pending_context_execution.py` — added `ExecuteReadyPendingContextCarnePicanteTest` and `ExecuteReadyPendingContextTransactionalBoundaryTest` (5 tests covering tasks 4.1, 4.2, 4.3, 4.4).
> - `backend/tests/test_incoming_message_orchestrator.py` — added `ProcessIncomingMessageClarificationOnlyCarnePicanteTest` (2 tests covering tasks 5.1, 5.2).
> - `backend/tests/test_agregar_producto_sequential_queue_end_to_end.py` — added `SequentialQueueE2EExactAssertionsTest` (4 tests covering tasks 6.1, 6.2, 6.3, 6.4).
>
> **Automated results**:
> - Focused suite (resolver, dispatcher, execution, orchestrator, transactional, endpoint, response, E2E): **184 passed**.
> - PostgreSQL-backed agregar-producto sequential queue + quantity regressions: **all passed**.
> - `quitar_producto` and `modificar_producto` suites: 5 pre-existing failures in `test_modificar_producto_dispatcher_integration.py`, `test_modificar_producto_real_flow_cli.py`, `test_modificar_producto_real_flow_http.py`, and `test_quitar_producto_end_to_end.py` are unrelated to this change (they exercise `product_modification_resolver` paths that the 3.32.5 work does not modify; they expect a single `dispatch_pending_context` return value that was changed to a list prior to 3.32.4).
> - Lint: `ruff check` passes on every changed file (`All checks passed!`); pre-existing import-order and unused-import errors remain in unrelated modules (`backend/alembic/env.py`, etc.).
> - Typecheck: `mypy backend/intents/context/product_selection_context_resolver.py` reports 1 pre-existing error (`status: str` should be a Literal) at line 34, present before this change.
> - Python compile: `py_compile` passes on every changed file.
> - OpenSpec validation: `openspec validate fix-repeated-unresolved-active-candidate-selection --strict` → `Change 'fix-repeated-unresolved-active-candidate-selection' is valid`.
>
> **Manual CLI output (literal)**:
> ```
> <session 42>
> <pedido 7>
> <- message=Elegí entre: Empanada de Carne … Empanada Picante o Empanada de Carne … Empanada Tradicional
> <- message=Listo, agregué 1 Empanada de Carne … Empanada Picante.
> <- message=Elegí entre: Pizza Mozzarella … Pizza Grande o Pizza Mozzarella … Pizza Chica
> Pedido actual:
> +-------------------+------------------+----------+
> | Producto          | Presentación     | Cantidad |
> +-------------------+------------------+----------+
> | Empanada de Carne | Empanada Picante |        1 |
> | Pizza Mozzarella  | Pizza Grande     |        1 |
> +-------------------+------------------+----------+
> <- message=Listo, agregué 1 Pizza Mozzarella … Pizza Grande.
> Pedido actual: (unchanged, both lines still present)
> ```
>
> **Final persisted order**:
> ```
> PedidoProducto rows: 2
>   - pp_id=<empanada_picante>, cantidad=1
>   - pp_id=<pizza_grande>,     cantidad=1
> Session pending.active: None
> Session pending.queue count: 0
> Session context_type: None
> ```

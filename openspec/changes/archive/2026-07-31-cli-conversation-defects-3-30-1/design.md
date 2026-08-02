## Context

Subphase 3.30 shipped a standalone CLI HTTP client (`backend/scripts/cli_chat_client.py`) that opens a `POST /sessions` session, replays every typed line through `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages`, prints the responses, and closes the session on `exit`. The 3.30 tests cover the CLI's standard-library-only contract and the read-eval-print loop, but they do not exercise a complete `agregar_producto` conversation against a real catalog.

When a developer runs the CLI manually against a seeded catalog (e.g. the five-pizza catalog of three `pizza ... grande` and two `pizza ... chica` presentations), three defects surface:

1. **Missing draft `Pedido` on the session.** `POST /sessions` creates a session with `id_pedido = null`. The modern `execute_agregar_producto` handler (subphase 3.16) raises `PedidoProductoNotEditable` / `PedidoProductoNotFound` indirectly via `PedidoProductoService.add` when `session.id_pedido is None`, and the handler returns `status == "rejected"` with the reason mapped to that condition. The CLI never sees a positive `executed`; every refined reply is rejected.
2. **Stale pending context after a deterministic `rejected` outcome.** `execute_ready_pending_context` (subphase 3.17) only clears `session.pending_intents` and `session.context_type` on `executed`. A `rejected` result (e.g. missing `pedido_id`) leaves `context_type = "product_selection"` and an active `ready` intent pinned. The next unrelated message is routed through `dispatch_pending_context` and is rejected by the same handler. The conversation enters a permanent rejection loop.
3. **Partial-candidate recognition does not narrow the active intent.** `resolve_product_selection` (subphase 3.12) only handles the "one unique match in `encontrados`" case. When the user replies with a partial narrowing (e.g. `"la grande"` against five pizza candidates, yielding three large presentations in `encontrados_posibles`), the resolver returns the input intent unchanged. The conversation cannot progress without a unique match, and the user is forced to type the exact full product name.

The modern pipeline's composability is preserved: the fixes are local to the CLI's bootstrap, the execution boundary, and the resolver. No new layers, no new endpoints, no new repositories, no new services, no new tests beyond the regression coverage.

## Goals / Non-Goals

**Goals:**

- The CLI creates a draft `Pedido` and binds it to the session it created, so the modern handler layer finds `session.id_pedido` set and a successful `agregar_producto` refinement lands as `executed`.
- The CLI still closes only the session it created AND the pedido it created (the pedido is closed transitively via the cascade-on-delete from the session — already implemented in 2.13).
- A definitive `rejected` handler result clears the pending context, so the next unrelated message re-enters initial classification instead of staying pinned to the dead intent.
- The `failed` handler result preserves pending context (transient technical failure — the user may want to retry).
- A raised technical exception inside the handler still propagates unchanged so the transactional wrapper's `db.rollback()` is preserved.
- The product-selection resolver narrows `candidate_ids` on partial matches, transitioning to `ready` when refinement leaves exactly one candidate (the dispatcher then executes in the same turn).
- The regression coverage locks the five-message `agregar_producto` conversation against `supernova_test` with a real catalog, plus the supporting scenarios (exact unique candidate, definitive rejected, next unrelated message, raised technical exception, CLI cleanup).

**Non-Goals:**

- Multi-intent CLI UX (e.g. listing multiple intents per response, threading).
- Thread / session switching inside a single CLI run.
- Session resume (continuing a previous session instead of creating a new one).
- A new session model field, a new pedido model field, a new schema, a new endpoint, a new router, a new service, a new repository, a new handler, a new recognizer, a new contract, a new orchestrator, a new middleware, a new dependency.
- Any model-level change, Alembic migration, Alembic env.py change, or seed change.
- Any change to the LLM, the `IntentClassifier`, the `QueryLlm`, the `CustomerResponse` builder, the response orchestrator, the transactional wrapper, the pending-context service, the pending-context dispatcher, the `execute_agregar_producto` handler body, the `pedido_producto` service, the `pedido` service, the `session` service, the `cliente` service, the `comercio` service, the `producto_query` service, the `producto_query` repository, the recognizer, the processor, the resolver (other than the narrowing branch), or any router.
- HTML, WebSocket, Twilio, async, queue, retry, backoff, logging, configuration, locale, template engines, response beautification.
- Phase 4 work.

## Decisions

### Decision 1 — CLI bootstrap creates the draft `Pedido` through the existing HTTP API

The CLI's `_create_session` is replaced with a bootstrap that calls three HTTP endpoints in sequence, using only `urllib.request` and the existing patterns in the script:

1. `POST /sessions` with `{"id_comercio": ..., "id_cliente": ...}` — returns the session id (`201`).
2. `POST /pedidos` with `{"id_session": <session_id>}` — returns the pedido id (`201`). The pedido is created in `borrador` and is already linked to the session via `pedidos.id_session`.
3. `PUT /sessions/{session_id}/pedido` with `{"id_pedido": <pedido_id>}` — sets `sessions.id_pedido` so the running pipeline sees the same value the handler reads. The endpoint validates that the pedido's comercio/cliente match the session's comercio/cliente and that the pedido is in `borrador`; both checks pass because the pedido was just created for the same pair.

The CLI does NOT import SQLAlchemy, repositories, services, or any module other than the standard library. The pedido `id_pedido` is held in memory alongside the `session_id` for the duration of the conversation; it is never written to disk and is not used by the read-eval-print loop (the loop only sends `message` to `/incoming-messages`).

**Why three endpoints and not just two?** `POST /pedidos` only sets `pedidos.id_session`. The handler in subphase 3.16 reads `conversation_session.id_pedido` (not `pedido.id_session`); that field is set by `PUT /sessions/{id}/pedido`. Both endpoints are required by the existing data model to ensure the two sides are consistent.

**Why not a new "create session with pedido" endpoint?** Out of scope. The existing two endpoints are sufficient and proven; the CLI's strict out-of-bounds rules forbid direct DB access.

**Error handling.** If any of the three endpoints fails with a non-2xx status, the CLI closes the session it created (via `POST /sessions/{id}/cerrar`) and exits non-zero. The error message is the `detail` field of the failed response.

**Alternative considered.** CLI calls `POST /sessions` with `id_pedido` already set. **Rejected** — the existing `POST /sessions` schema places `id_pedido` as an optional pointer (`PUT /sessions/{id}/pedido` is the source of truth for the association), and changing the semantics of `POST /sessions` would be a breaking change to the session-api capability.

### Decision 2 — `execute_ready_pending_context` clears pending context on `rejected` in addition to `executed`

The current code is:

```python
if result.status == "executed":
    clear_pending_context(session)
    session.context_type = None
return result
```

Replaced with:

```python
if result.status in ("executed", "rejected"):
    clear_pending_context(session)
    session.context_type = None
return result
```

`failed` continues to preserve pending context. A raised exception inside `execute_agregar_producto` (the only handler currently dispatched) is caught by the handler and rewritten to `failed` before reaching this boundary; an exception that escapes the handler propagates unchanged so the transactional wrapper's `db.rollback()` still fires.

**Why clear on `rejected` and not on `failed`?** `rejected` is a definitive business outcome — the handler has decided the intent cannot be executed (e.g. missing `pedido_id`, invalid `cantidad`, missing presentation). `failed` is a transient technical outcome (e.g. `IntegrityError` from a database race) that may be retried after the underlying issue is fixed. The submodule's 3.17 contract already encoded this distinction; the 3.17 design was too conservative and the 3.30.1 manual testing exposes the practical defect.

**Alternative considered.** Distinguish "definitive rejected" from "transient rejected" inside the handler. **Rejected** — the handler already maps `PedidoNotFound`, `PedidoNotEditable`, `PrecioNotFound`, `ProductoPresentacionNotFound`, and missing `pedido_id` to `rejected`. All of these are definitive business outcomes; the user cannot retry them by typing a different message. The four `except` arms don't need to be split.

### Decision 3 — `resolve_product_selection` narrows `candidate_ids` on partial matches

The current unique-selection path is reused:

```python
if len(resultado["encontrados"]) == 1:
    selected_id = resultado["encontrados"][0]["producto_presentacion_id"]
    if selected_id not in active_intent.candidate_ids:
        return active_intent
    # apply unique selection
```

A new branch is added BEFORE the early-exit on `len(encontrados) != 1`:

```python
if len(resultado["encontrados"]) == 0 and resultado["encontrados_posibles"]:
    matched_ids: list[int] = []
    for group in resultado["encontrados_posibles"]:
        for product in group.get("productos", []):
            matched_ids.append(product["producto_presentacion_id"])
    intersection = [cid for cid in matched_ids if cid in active_intent.candidate_ids]
    if not intersection:
        return active_intent
    if len(intersection) == 1:
        # reuse the unique-selection path: build the resolved intent with the
        # remaining id, mark the requirement completed, clear candidate_ids,
        # set status to "ready" if all requirements are completed.
        ...
    # >1 candidates: narrow candidate_ids to the intersection and keep
    # status == "pending_resolution"
    return active_intent.model_copy(update={"candidate_ids": intersection})
```

The `encontrados` (unique) branch takes priority: if the recognizer returns exactly one confident match, the unique-selection path is used even when there are also candidates. The narrowing branch only fires when there are zero confident matches and at least one candidate group.

**Why preserve order?** `candidate_ids` is a list, not a set. The narrowed list preserves the original order of `active_intent.candidate_ids` (filtered by the intersection) so the dispatcher's downstream behavior matches the existing "ordered list" semantics documented in subphase 3.4.

**Why not narrow `resolved_data`?** `resolved_data` carries per-slot values (e.g. `cantidad`). Narrowing `candidate_ids` is the only state that needs to change because the message only affects which presentations are still in play.

**Why return the input unchanged on empty intersection?** Defensive: a partial narrowing that yields zero candidates means the user replied with something that doesn't match any of the original candidates (e.g. they typed "la grande" when the original candidates were all `chica`). Returning unchanged keeps the original candidates list so the user can correct their message. Returning empty would lose the conversation context.

**Alternative considered.** Reject the input intent with `status == "rejected"` on empty intersection. **Rejected** — the user could still type a corrective message and the conversation should not end on a single bad reply. Returning unchanged is the existing pattern for "ambiguous, unavailable, unknown" results.

### Decision 4 — Regression coverage lives in a new test module that pre-seeds the catalog

The new test module `backend/tests/test_cli_conversation_regression.py` uses the same `engine` / `TestingSessionLocal` pattern as `backend/tests/test_incoming_message_integration.py` (subphase 3.25). It seeds five presentations (three `pizza ... grande`, two `pizza ... chica`) under a single categoria and producto, runs the real CLI loop over HTTP against `supernova_test`, and asserts the five-message flow described in the proposal.

The CLI's standard-library-only boundary is preserved. The test imports the CLI as a module and drives `main()` via `input()` patching (the same pattern as `backend/tests/test_cli_chat_client.py`).

**Why a new test module instead of extending `test_cli_chat_client.py`?** The existing module covers the CLI's HTTP contract (urllib call patterns, base-URL resolution, exit handler). The new module covers the end-to-end business conversation against a real database with a real catalog. Keeping these two concerns separate avoids polluting the unit-style tests with database fixtures.

**Why pre-seed the catalog instead of mocking the recognizer?** The user's regression flow includes the `"la grande"` message that depends on the real `detectar_productos` tokenizer (the `TAMANIOS` token filter would swallow `grande` without a product noun otherwise). The real recognizer is the only way to exercise the narrowing branch end-to-end.

## Risks / Trade-offs

- **[Risk] Tightening the CLI's HTTP contract may break developers who scripted against the 3.30 version.** The 3.30 spec says the CLI issues exactly two HTTP calls per typed line (POST /sessions + POST /incoming-messages). The 3.30.1 spec adds two more bootstrap calls (POST /pedidos + PUT /sessions/{id}/pedido). → **Mitigation**: the spec delta explicitly documents the new sequence. The two-call iterative path is unchanged. Any external script that relied on counting POST /sessions calls is unaffected.

- **[Risk] Clearing pending context on `rejected` may mask a legitimate debugging scenario.** A developer who manually injects a bad pedido_id expects to see the rejection repeatedly. → **Mitigation**: the developer can re-create the session via the CLI (one session per CLI run). The change is consistent with the user's intent (the CLI is a manual iteration tool, not a long-lived test harness).

- **[Risk] The narrowing branch may produce a `ready` intent that the handler calls `"rejected"` because the chosen presentation is unavailable.** → **Mitigation**: the existing `execute_agregar_producto` already returns `rejected` for `ProductoPresentacionNotFound`; the new "cleared on rejected" branch then unsticks the conversation. The narrowing does not bypass the business validation.

- **[Risk] The intersection computation does not deduplicate ids.** If the recognizer returns the same id twice in `encontrados_posibles` (e.g. two product groups share a presentation), the intersection will contain the id twice. → **Mitigation**: the narrowing preserves order, not uniqueness; the existing `process_agregar_producto` processor reads `candidate_ids` as an ordered list. The downstream handler uses the id to look up the product presentation, so duplicates are inert. Documented in the resolver's spec delta.

- **[Risk] The `_cerrar` failure handler in the CLI may swallow transient network errors that were previously recoverable.** The 3.30 spec says the close failure is non-fatal (single warning line, exit 0). The 3.30.1 spec preserves this behavior. → **Mitigation**: no change. The CLI's existing `try/except Exception` around `_post_json` already swallows network errors during close.

- **[Risk] The new test module increases the integration test runtime.** The integration tests in `backend/tests/test_incoming_message_integration.py` already run against `supernova_test` and take ~1s each. The new module adds at most 5 conversation scenarios plus fixtures. → **Mitigation**: the new module only runs in the focused CLI conversation suite and is not part of the smoke test runner. The existing unit tests for the CLI, the resolver, and the execution boundary are unaffected.

- **[Risk] The CLI's `_create_session` rename to `_bootstrap_session` (or kept as `_create_session`) is a tiny refactor with no runtime impact.** → **Mitigation**: keep the existing symbol name `_create_session`; extend its body to issue the three bootstrap calls. The change is additive within the function.

## Migration Plan

This is a bug-fix subphase. There is no migration, no data backfill, no schema change, no model change, no Alembic migration, no seed change, no deployment step beyond redeploying the updated CLI script and the updated `backend/intents/orchestration/pending_context_execution.py` and `backend/intents/context/product_selection_context_resolver.py` modules.

**Rollback strategy.** Revert the three file changes (`backend/scripts/cli_chat_client.py`, `backend/intents/orchestration/pending_context_execution.py`, `backend/intents/context/product_selection_context_resolver.py`) and the related test changes. The pre-3.30.1 behavior is preserved on disk. No external state is touched.

**Deployment order.** Standard `supernova` redeploy (the FastAPI server picks up the new module bodies; the CLI script is a pure Python script that operators run on demand). The CLI bootstrap will now create one session + one pedido per run; both are closed on `exit` (the pedido is closed transitively via the existing cascade-on-delete from the session).

## Open Questions

None. The three defects are well-defined and the fixes are constrained to the existing modules. The regression flow is concrete. The user's scope explicitly forbade multi-intent UX, thread/session switching, session resume, HTML, WebSocket, and Twilio; the design honors those constraints.

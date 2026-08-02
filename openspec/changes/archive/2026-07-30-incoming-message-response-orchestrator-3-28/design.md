## Context

The modern intents pipeline has stabilized across Subphases 3.22 → 3.27:

- `process_incoming_message(db, session, message)` (3.24) validates the message and routes to `dispatch_pending_context` or `dispatch_initial_message`, returning a `list[ProcessedIntent]` with statuses `pending_resolution`, `ready`, `executed`, `rejected`, or `failed`.
- `process_incoming_message_transactional(db, session, message)` (3.26) wraps that call with `db.commit()` on success and `db.rollback()` then bare `raise` on any exception; it is the modern transaction boundary for inbound messages.
- `build_agregar_producto_response(db, session, intent)` (3.27) is the deterministic customer-facing shaper for `agregar_producto`; it covers `pending_resolution` (clarification), `executed` (confirmation), `rejected` (apology), and `failed` (retry) and returns a generic apology for any non-`agregar_producto` intent.

Until now the pipeline had no seam that ran the transaction and turned the returned intents into a `list[CustomerResponse]`. Subphase 3.28 introduces that seam as a thin, deterministic orchestrator that:

- Calls the existing transactional processor exactly once.
- Iterates the returned `ProcessedIntent` list in order.
- Routes `intent == "agregar_producto"` to the existing response builder.
- Returns a deterministic generic `CustomerResponse` (preserving `intent` and `status`) for every other intent.
- Does not perform another commit / rollback, does not query SQLAlchemy, does not import repositories / LLM / HTTP / Twilio, and does not introduce response builders for new intents.

This orchestrator is the single modern front door for callers that want both the transactional boundary and the customer-visible strings. Future Twilio / FastAPI adapters, background workers, and test harnesses should call `process_incoming_message_with_responses` and stop branching on intent names themselves.

## Goals / Non-Goals

**Goals:**

- Expose `process_incoming_message_with_responses(db: DatabaseSession, session: ConversationSession, message: str) -> list[CustomerResponse]` from `backend/intents/orchestration/incoming_message_response_orchestrator.py` as the single deterministic seam that runs the modern transactional pipeline and converts its output into customer-facing strings.
- Use the typed-alias convention `Session as DatabaseSession` from `sqlalchemy.orm` and `Session as ConversationSession` from `backend.models.session` — same aliases as `process_incoming_message`, `process_incoming_message_transactional`, and `build_agregar_producto_response`.
- Call `process_incoming_message_transactional(db, session, message)` exactly once per invocation. Preserve the order of its `list[ProcessedIntent]` return value.
- For each `ProcessedIntent`, dispatch on `intent.intent`:
  - `intent == "agregar_producto"`: append the `CustomerResponse` returned by `build_agregar_producto_response(db, session, intent)`.
  - any other `intent`: append a generic `CustomerResponse(message=GENERIC_MESSAGE, intent=<intent>, status=<status>)` that preserves the original `intent` and `status`. The generic message must be deterministic, free of IDs, exception details, and technical context.
- Return a `list[CustomerResponse]` whose length equals the inner `list[ProcessedIntent]` length and whose order matches the inner list order (including the order of mixed executed / rejected / failed items).
- Propagate every exception raised by the inner transactional processor unchanged: no wrapping, no conversion, no swallowing, no `HTTPException` translation, no extra commit / rollback call.
- Stay free of SQLAlchemy queries, repository access, LLM calls, HTTP / Twilio integration, `db.commit` / `db.rollback` / `db.flush` / `db.refresh` / `db.expire` / `db.begin` calls, response beautification, locale selection, template engines, logging, retry / backoff, async wrappers, caching, queue promotion, and imports from `backend.old_project`, `backend.routers`, `backend.sessions`, `backend.dependencies`, `backend.llm`, recognizers, resolvers, processors, handlers, services, context, and queue modules.
- Add focused tests in `backend/tests/test_incoming_message_response_orchestrator.py` that mock `process_incoming_message_transactional` and `build_agregar_producto_response` to lock the per-intent routing, order preservation, exception propagation, and absence of new commit / rollback calls.

**Non-Goals:**

- Implementing response builders for additional intents (`consultar_pedido`, `confirmar_pedido`, `cancelar_pedido`, etc.).
- Replacing or duplicating the transaction boundary owned by `process_incoming_message_transactional`.
- Replacing or duplicating the per-intent message shaping owned by `build_agregar_producto_response`.
- Generating responses via LLM, templates, locale, message-formatting libraries, or any HTTP / Twilio surface.
- Sending replies over Twilio, WhatsApp, FastAPI, HTTP, or any transport layer.
- Mutating `Session` (`pending_intents`, `context_type`, `id_pedido`), `Pedido`, `PedidoProducto`, or any `ProcessedIntent`.
- Refreshing, expiring, flushing, committing, or rolling back the SQLAlchemy session.
- Adding a registry, a factory, a multi-intent dispatcher, or any extra public helper to the new module.
- Modifying `backend/intents/orchestration/{incoming_message_orchestrator,initial_intent_dispatcher,pending_context_dispatcher,pending_context_execution,agregar_producto_orchestrator,transactional_message_processor}.py`, `backend/intents/responses/agregar_producto_response.py`, `backend/intents/schemas/{customer_response,processed_intent}.py`, `backend/intents/handlers/*`, `backend/intents/context/*`, `backend/intents/recognizers/*`, `backend/intents/resolvers/*`, `backend/intents/processor.py`, `backend/intents/contracts/*`, `backend/services/*`, `backend/repositories/*`, `backend/llm/*`, `backend/routers/*`, `backend/dependencies.py`, models, migrations, or configuration.

## Decisions

- **Module location: `backend/intents/orchestration/incoming_message_response_orchestrator.py`.** Sits next to `incoming_message_orchestrator.py`, `initial_intent_dispatcher.py`, `pending_context_dispatcher.py`, `pending_context_execution.py`, `agregar_producto_orchestrator.py`, and `transactional_message_processor.py`. Rationale: the new function is the orchestration-level bridge between the transactional processor and the customer-facing shaper; placing it next to its sibling orchestrators keeps the entry-point surface discoverable and avoids growing the `responses/` package with a dispatcher-shaped function.

- **Single public function: `process_incoming_message_with_responses`.** `__all__ = ["process_incoming_message_with_responses"]`. Rationale: future Twilio / FastAPI adapters need exactly one deterministic seam; exposing helpers now would force future changes to deprecate them. Mirrors the discipline of `process_incoming_message`, `process_incoming_message_transactional`, `dispatch_initial_message`, `dispatch_pending_context`, `process_initial_agregar_producto`, and `build_agregar_producto_response`.

- **Typing aliases for the two `Session` meanings.** Use `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model. Rationale: same aliases already used in `agregar_producto_orchestrator.py`, `incoming_message_orchestrator.py`, `pending_context_dispatcher.py`, `execute_agregar_producto`, `process_incoming_message_transactional`, and `build_agregar_producto_response`; keeps the call site readable and avoids shadowing the most-imported symbol.

- **Delegate the full message lifecycle to `process_incoming_message_transactional`.** The orchestrator calls it exactly once; it does not re-validate the message, does not re-route on `session.context_type`, does not call `dispatch_initial_message` or `dispatch_pending_context` directly, and does not perform its own commit / rollback. Rationale: Subphase 3.26 owns the transaction boundary; duplicating it here would create two competing commit points. The new function is a thin pipeline wrapper that adds response shaping on top of an already-committed (or already-rolled-back) result.

- **Per-`intent.intent` dispatch via literal `if/elif`.** A literal `if/elif` chain on `intent.intent` is used in place of any registry, dict, or strategy pattern. The current branch is `if intent.intent == "agregar_producto": ... elif else: GENERIC`. Rationale: the future work is one branch per new intent; a registry would have to be re-shaped every time anyway. Mirrors the discipline of `initial_intent_dispatcher.py` (Subphase 3.23) and `build_agregar_producto_response` (Subphase 3.27), which both use literal branches to keep the dispatch rule explicit and grep-able.

- **Deterministic generic fallback for unsupported intents.** A single module-level constant `GENERIC_MESSAGE` (Spanish, fixed apology sentence, no IDs, no exception text, no technical detail) is returned for every non-`agregar_producto` intent, with `intent=<intent>` and `status=<status>` preserved from the original `ProcessedIntent`. Rationale: the orchestrator must not crash on `desconocida`, `saludo`, `quitar_producto`, or any future intent that reaches it before a builder exists; the fallback keeps the response surface deterministic and the intent / status metadata recoverable for logging by the future transport adapter.

- **No mutation, no commit, no rollback, no flush, no refresh, no expire.** The orchestrator does not assign to `session.pending_intents`, `session.context_type`, `session.id_pedido`, or any field of an `intent`; the only outbound state change is constructing `CustomerResponse` instances and appending them to the returned list. The only SQLAlchemy session method invoked by this module is whatever `build_agregar_producto_response` calls internally (read-only via `ProductoQueryService.list_presentaciones_by_ids`); the wrapper itself calls `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, and `db.begin` zero times. Rationale: the project rule "no Session / Pedido / intent mutation outside the orchestrator / handler" is binding; the response orchestrator is downstream of all persistence and must remain a pure read.

- **No HTTP / Twilio / FastAPI / LLM / queue / handler imports.** The module imports only `sqlalchemy.orm.Session`, `backend.models.session.Session`, `backend.intents.schemas.customer_response.CustomerResponse`, `backend.intents.schemas.processed_intent.ProcessedIntent`, `backend.intents.orchestration.transactional_message_processor.process_incoming_message_transactional`, and `backend.intents.responses.agregar_producto_response.build_agregar_producto_response`. Rationale: the future transport adapter owns Twilio / FastAPI; the future queue dispatcher owns message delivery; the handler owns business execution; this orchestrator owns only the orchestration seam.

- **Tests use `MagicMock`-based stubs at the wrapper's import site.** A new `backend/tests/test_incoming_message_response_orchestrator.py` patches `process_incoming_message_transactional` and `build_agregar_producto_response` at `backend.intents.orchestration.incoming_message_response_orchestrator` so the suite exercises only the new function. No real LLM, database, or HTTP is invoked. Rationale: matches the discipline of `test_transactional_message_processor.py`, `test_incoming_message_orchestrator.py`, `test_initial_intent_dispatcher.py`, and `test_intent_classifier.py` — the wrapper's correctness is its routing logic, not the inner processors.

## Risks / Trade-offs

- [Risk] The `intents.orchestration` package now exports both `process_incoming_message` and `process_incoming_message_with_responses`; a future caller may pick the wrong one. → Mitigation: keep the naming distinct, document in the module docstring that the response-shaped variant is the entry point for any caller that needs customer strings, and leave the original `process_incoming_message` untouched for callers that only need the `ProcessedIntent` list (e.g. background workers that batch intents into analytics).

- [Risk] A future intent lands in the classifier before its response builder, leaving the orchestrator to fall through to the generic `GENERIC_MESSAGE` branch silently. → Mitigation: the literal `if/elif` chain makes the unsupported branch visible at code-review time; the `__all__` discipline keeps the public surface to one symbol so future drift is caught immediately; the focused tests assert the generic fallback's exact message and preserved `intent` / `status` so any new branch is detected by a missing test rather than a silent behavior change.

- [Risk] The orchestrator accidentally commits twice (once inside `process_incoming_message_transactional`, once in this module). → Mitigation: the tests assert `db.commit.assert_not_called()` and `db.rollback.assert_not_called()` on a `MagicMock(name="DatabaseSession")`, and the design section above is explicit that this module does not call any session-state method.

- [Risk] The generic `GENERIC_MESSAGE` leaks technical detail (exception types, IDs, stack traces) if the original `intent.status` is `"failed"` and the implementation tries to include the original exception text. → Mitigation: the generic message is a single fixed Spanish string with no placeholders, no formatting parameters, and no access to the original `intent`'s metadata beyond `intent` and `status`; the focused tests assert the literal text and assert no exception tokens (`"Exception"`, `"Traceback"`, `"Error"`, `"id"`) appear in the response.

- [Risk] Adding a sibling orchestrator increases the `intents.orchestration` package surface. → Mitigation: `__all__` discipline keeps the public surface to one function; the test suite asserts `__all__ == ["process_incoming_message_with_responses"]` so future drift is caught immediately.

- [Risk] Future subphases may want logging, retries, async wrappers, locale selection, or transport adapter hooks in this seam. → Mitigation: the non-goals section is explicit; the focused tests assert the module does not import `requests`, `fastapi`, `twilio`, `backend.routers`, `backend.sessions`, `backend.dependencies`, `backend.llm`, `backend.old_project`, recognizers, resolvers, processors, handlers, services, context, or any queue module.

## Migration Plan

1. Create `backend/intents/orchestration/incoming_message_response_orchestrator.py` with `__all__ = ["process_incoming_message_with_responses"]` and the typed-alias imports; implement `process_incoming_message_with_responses` per the literal-`if/elif` decision tree (one branch for `agregar_producto`, one for everything else) using `process_incoming_message_transactional` and `build_agregar_producto_response`; declare a single module-level `GENERIC_MESSAGE` constant.
2. Add `backend/tests/test_incoming_message_response_orchestrator.py` covering: `agregar_producto` routes to the response builder, unsupported intent returns the generic `CustomerResponse` with preserved `intent` and `status`, multi-intent list preserves order, exception from the transactional processor propagates unchanged, `__all__` discipline, source-code boundary checks (no `sqlalchemy.select`, no `joinedload`, no `requests`, no `fastapi`, no `twilio`, no `backend.routers`, no `backend.sessions`, no `backend.llm`, no `backend.old_project`, no `HTTPException`, no `JSONResponse`, no `MessagingResponse`, no `QueryLlm`, no `retry`, no `backoff`, no `async def`), no `db.commit` / `db.rollback` / `db.flush` / `db.refresh` / `db.expire` / `db.begin` calls, and no mutation of `session` / `intent`.
3. Wire the new test module into the project's standard test runner alongside `test_incoming_message_orchestrator.py`, `test_transactional_message_processor.py`, and `test_incoming_message_integration.py`.
4. Run `PYTHONPATH=. venv/bin/python backend/tests/test_incoming_message_response_orchestrator.py` and confirm all checks pass without a real LLM, database, or HTTP.
5. Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm exit 0.
6. Run `openspec validate incoming-message-response-orchestrator-3-28 --strict` and confirm valid.
7. Roll back by deleting the new files; no other module imports `process_incoming_message_with_responses`, so no ripple effects.

## Open Questions

None.
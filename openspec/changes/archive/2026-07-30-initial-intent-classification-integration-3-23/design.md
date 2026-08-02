## Context

Subphase 3.22 finalized `IntentClassifier` — a thin consumer of `QueryLlm` that turns a raw message string into an `IntentClassificationResult` — and the modern intents pipeline already has two orchestration entry points in place:

- `backend/intents/orchestration/agregar_producto_orchestrator.py` exposes `process_initial_agregar_producto(db, session, source_text) -> ProcessedIntent` (Subphase 3.15). It owns commerce-scoped catalog loading, recognition, resolution, processing, and conditional pending-context persistence for the `agregar_producto` flow.
- `backend/intents/orchestration/pending_context_dispatcher.py` exposes `dispatch_pending_context(db, session, message) -> ProcessedIntent` (Subphase 3.18). It owns dispatch into the active `product_selection` context once the classifier or a previous orchestrator has already established one.

Neither module owns the upstream step of "take a fresh inbound message and turn it into one or more `ProcessedIntent` values". Until now, every consumer would need to construct an `IntentClassifier`, call `query(message)`, then branch by `IntentName`. That violates the project rule that orchestration entry points absorb LLM/recognition/catalog coordination away from callers.

The classifier already returns an `IntentClassificationResult.intents` list (preserving order, non-empty), and `process_initial_agregar_producto` already returns the typed `ProcessedIntent` we need to propagate. Subphase 3.23 connects them with a single new dispatcher so the modern intents pipeline has one obvious entry point for fresh messages.

## Goals / Non-Goals

**Goals:**
- Expose `dispatch_initial_message(db, session, message) -> list[ProcessedIntent]` as the only modern entry point for fresh inbound messages.
- Use the modern `IntentClassifier` to classify `message`; preserve the classified-intent order in the returned list.
- Forward `agregar_producto` items to the existing `process_initial_agregar_producto` and return its `ProcessedIntent`.
- For `desconocida` or any other currently unsupported intent, return a `ProcessedIntent` with `status="rejected"` — never invoke any orchestrator or handler.
- Refuse to classify/dispatch when `session.context_type` is already set; pending-context messages must continue to flow through `dispatch_pending_context`.
- Stay free of SQLAlchemy queries, repository access, `commit`/`rollback`, FastAPI, or customer-response generation; the dispatcher only orchestrates the classifier and existing orchestrators.
- Be testable with a stub `IntentClassifier` and a stub orchestrator; no real LLM call and no `supernova_test` connection required for the dispatcher unit tests.

**Non-Goals:**
- Adding new intents, recognizers, resolvers, processors, handlers, or contracts.
- Modifying `IntentClassifier`'s prompt, catalog, logging, or constructor.
- Modifying `process_initial_agregar_producto`, `dispatch_pending_context`, or any pending-context service.
- Implementing a `dispatch_initial_message` route, dependency, or background task.
- Implementing a unified router that chooses between initial and pending dispatch; that belongs to a future subphase.
- Logging, retry/backoff, async, caching, multi-message history, or conversation summarization.
- Touching `backend/llm/query_llm.py`, `backend/intents/schemas/intent_classification.py`, `backend/config/settings.py`, routers, dependencies, services, repositories, models, or migrations.

## Decisions

- **Module location: `backend/intents/orchestration/initial_intent_dispatcher.py`.** Sits next to `agregar_producto_orchestrator.py` and `pending_context_dispatcher.py` so all three orchestration entry points share one directory. The package is the project's existing home for LLM-aware, database-aware coordinators that sit between classification and execution.

- **Public surface: a single module-level function.** `dispatch_initial_message(db, session, message) -> list[ProcessedIntent]` is the only export; `__all__ = ["dispatch_initial_message"]` keeps the contract narrow and mirror's sibling dispatchers' discipline.

- **Typing aliases for the two `Session` meanings.** Keep `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model — the same aliases already used in `agregar_producto_orchestrator.py`. This avoids shadowing the most-imported symbol in the module.

- **Guard ordering: pending context first.** The function checks `session.context_type is not None` before doing any classification. If a pending context is active, it returns `[]` — the caller must route to `dispatch_pending_context`. Rationale: keep classifier traffic minimal, keep contract clear, and avoid a race where `query(message)` would have side-effects (none here, but the rule documents intent).

- **Classifier construction: `IntentClassifier()` by default.** Construct the classifier directly inside the function with no module-level singleton so tests can monkey-patch the constructor or use a stub. The function does not take a classifier parameter (matches the existing orchestrator's signature shape and keeps the public contract simple).

- **Order preservation by list iteration.** Iterate `result.intents` in the order returned by the classifier and append one `ProcessedIntent` per item. The classifier schema already enforces non-empty, ordered intent lists.

- **Per-intent dispatch table is a literal `if/elif` chain, not a registry.** Only `agregar_producto` is currently supported; everything else falls through to the rejected branch. A registry would anticipate future subphases that this change is explicitly not adding. A single `if name == IntentName.AGREGAR_PRODUCTO` branch is sufficient and stays honest.

- **Rejection shape: a fresh `ProcessedIntent` per item, never the input message.** Rejection items reuse `classified.intent` for `intent` and `classified.mensaje` for `source_text` (the text the LLM attached to that intent), with `status="rejected"`, the recognized `recognizer="intent_classifier"`, and the per-intent handler name (`agregar_producto` for `agregar_producto`, otherwise the intent name itself). `resolved_data`, `requirements`, and `candidate_ids` use their schema defaults. Rationale: matches `dispatch_pending_context._rejected_copy` discipline — the rejected items carry everything the caller needs to log or format a user reply, but no execution happened.

- **Rejection handler-name rule for unsupported intents.** For `agregar_producto` rejections, the handler name is `"agregar_producto"` (mirrors `dispatch_pending_context`'s rejection literal). For all other unsupported intents, the handler name is the intent name string itself (no contract exists, so the intent name is the most accurate label). Both match `processed-intent-schema.spec.md`'s "handler is a `str`" requirement.

- **No logging in this module.** The classifier already logs `start`/`success`/`failure`; the orchestrator already returns structured `ProcessedIntent` results. Adding a third logging layer would duplicate events without adding visibility. If a future caller needs a single audit trail it can wrap `dispatch_initial_message` from outside.

- **Tests: `unittest.TestCase` with stubs, no real LLM, no `supernova_test` connection.** Match the style of `backend/tests/test_intent_classifier.py` and the existing intent tests. The test module patches `IntentClassifier` at the dispatcher module's import site (`backend.intents.orchestration.initial_intent_dispatcher.IntentClassifier`) and patches `process_initial_agregar_producto` with a `Mock` returning a `ProcessedIntent` stub. No DB session is opened beyond passing a `MagicMock(name="DatabaseSession")`.

## Risks / Trade-offs

- [Risk] Callers may invoke `dispatch_initial_message` while a pending context is active → Mitigation: the dispatcher short-circuits to `[]` whenever `session.context_type is not None`; the change documents this explicitly so future callers know to route via `dispatch_pending_context` instead.

- [Risk] Adding `IntentClassifier()` inside the function changes observable behavior if the caller previously expected a single classifier instance to be reused → Mitigation: the project context explicitly forbids module-level mutable state for the classifier (`query()` carries no retained state), and no existing caller imports it; the only side-effect is per-call log lines from the classifier, which is the intended audit trail.

- [Risk] Constructing a fresh `ProcessedIntent` for each rejected item might be inconsistent with `dispatch_pending_context._rejected_copy` (which uses `model_copy`) → Mitigation: `dispatch_pending_context` has an existing `ProcessedIntent` to copy from; `dispatch_initial_message` does not, so a fresh construction is the honest equivalent. Both share `status="rejected"` and identical defaults for `resolved_data`/`requirements`/`candidate_ids`.

- [Risk] Future subphases may add new supported intents and break the `if/elif` shape → Mitigation: the change is intentionally a literal chain (`if`/`elif`/`else`) and intentionally not a registry. Adding a new supported intent will require a code change in this file in the future subphase that introduces the orchestration for it; that is the desired friction.

- [Risk] Returning `list[ProcessedIntent]` (rather than one `ProcessedIntent` or a tuple) hides the multi-intent case from naive callers → Mitigation: the type annotation is explicit; the test suite asserts one-returned item per classified item so callers cannot accidentally ignore items.

## Migration Plan

1. Add `backend/intents/orchestration/initial_intent_dispatcher.py` exporting `dispatch_initial_message` with the documented signature and behavior; do not touch any other module.
2. Add `backend/tests/test_initial_intent_dispatcher.py` with stub `IntentClassifier` and stub `process_initial_agregar_producto`; cover `agregar_producto`, multi-intent order, `desconocida` rejection, unsupported-intent rejection, the active-pending-context guard, and the no-commit guarantee.
3. Run only the new test module: `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_initial_intent_dispatcher`.
4. Run `PYTHONPATH=. venv/bin/python -m compileall backend` to catch syntax errors.
5. Roll back by deleting the new module and its test file; no other module imports them, so no ripple effects.

## Open Questions

None.

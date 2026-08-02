## Why

Subphases 3.20–3.22 produced the modern classification building blocks — `IntentName`, `ClassifiedIntent`, `IntentClassificationResult`, `QueryLlm`, and `IntentClassifier` — but no module in the modern stack actually turns a free-form client message into a `ProcessedIntent`. Subphase 3.15 already shipped `process_initial_agregar_producto` for the first intent, and Subphase 3.18 shipped `dispatch_pending_context`, but the entry point that classifies a fresh inbound message and forwards the result to the existing orchestrator is still missing. Without it, the modern intents pipeline cannot consume the work the classifier produces.

## What Changes

- Add `backend/intents/orchestration/initial_intent_dispatcher.py` exporting `dispatch_initial_message(db, session, message: str) -> list[ProcessedIntent]`.
- Call `IntentClassifier` to validate and classify the inbound `message`, preserving the classified-intent order returned by the classifier.
- For each classified item, dispatch via the existing flow:
  - `agregar_producto` → invoke `process_initial_agregar_producto(db, session, classified.mensaje)` and use its `ProcessedIntent`.
  - `desconocida` or any other currently unsupported intent → return a `ProcessedIntent` with `status="rejected"`; do not invoke any orchestrator or handler.
- Reject the dispatch before classification when `session.context_type` is already set; pending-context messages route through `dispatch_pending_context`, not the initial dispatcher.
- Add focused unit tests in `backend/tests/test_initial_intent_dispatcher.py` using a stub `IntentClassifier` (no real LLM, no real orchestrator side-effects). Cover `agregar_producto` dispatch, multi-intent order preservation, `desconocida` rejection, unsupported-intent rejection, and the active-pending-context guard.

## Capabilities

### New Capabilities

- `initial-intent-dispatcher`: Defines the initial-message dispatch entry point that connects the modern `IntentClassifier` to the existing `agregar_producto` orchestrator, preserves classified intent order, rejects `desconocida` and other currently unsupported intents, and refuses to dispatch when a pending context is already active.

### Modified Capabilities

- `agregar-producto-intent-orchestration`: No requirement changes; remains the authoritative orchestrator for `agregar_producto`. The new dispatcher is a consumer of the existing `process_initial_agregar_producto` and introduces no new behavior on that side.
- `intent-classifier`: No requirement changes; remains the authoritative classification consumer of `QueryLlm`.

## Impact

- New module `backend/intents/orchestration/initial_intent_dispatcher.py` (sibling of `agregar_producto_orchestrator.py` and `pending_context_dispatcher.py`).
- New tests `backend/tests/test_initial_intent_dispatcher.py` with stub `IntentClassifier` and stub orchestrator; no real LLM call, no commit/rollback, no `Session` query.
- Reused unchanged: `backend/llm/intent_classifier.py`, `backend/intents/orchestration/agregar_producto_orchestrator.py`, `backend/intents/schemas/intent_classification.py`, `backend/intents/schemas/processed_intent.py`, `backend/models/session.py`, `backend/sessions/enums/context_type.py`.
- Not touched: recognizer, resolver, processor, handler, `dispatch_pending_context`, services, repositories, routers, dependencies, migrations, configuration.
- No new intents, no catalog changes, no prompt changes, no `QueryLlm` or `Session` interaction beyond what `process_initial_agregar_producto` already performs.
- Pending-context dispatch remains the responsibility of the existing `dispatch_pending_context` module; the new dispatcher does not overlap or supersede it.

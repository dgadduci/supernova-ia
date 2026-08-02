## 1. Dispatcher Implementation

- [x] 1.1 Create `backend/intents/orchestration/initial_intent_dispatcher.py` with `__all__ = ["dispatch_initial_message"]` and the documented imports: `Session as DatabaseSession` from `sqlalchemy.orm`, `Session as ConversationSession` from `backend.models.session`, `IntentClassifier` from `backend.llm.intent_classifier`, `IntentName` from `backend.intents.schemas.intent_classification`, `ProcessedIntent` from `backend.intents.schemas.processed_intent`, and `process_initial_agregar_producto` from `backend.intents.orchestration.agregar_producto_orchestrator`.
- [x] 1.2 Implement `dispatch_initial_message(db, session, message)` so it short-circuits to `[]` when `session.context_type is not None` and does NOT construct an `IntentClassifier` in that branch.
- [x] 1.3 Construct `IntentClassifier()` inside the dispatcher when the pending-context guard does not trigger; call `query(message)` exactly once; let `TypeError`, `ValueError`, `QueryLlmError`, and `pydantic.ValidationError` propagate unchanged.
- [x] 1.4 For each `ClassifiedIntent` in `result.intents`, in the order returned by the classifier: if `classified.intent == IntentName.AGREGAR_PRODUCTO`, call `process_initial_agregar_producto(db, session, classified.mensaje)` and append its return value; otherwise append a fresh `ProcessedIntent(intent=classified.intent.value, source_text=classified.mensaje, status="rejected", recognizer="intent_classifier", handler=classified.intent.value)` using the schema defaults for `resolved_data`, `requirements`, and `candidate_ids`.
- [x] 1.5 Return the accumulated list of one `ProcessedIntent` per classified intent.

## 2. Boundaries

- [x] 2.1 Keep the dispatcher free of `requests`, `fastapi`, `sqlalchemy.select`, `sqlalchemy.orm.selectinload`, repository imports, router imports, and `backend.sessions` imports.
- [x] 2.2 Do not call `db.commit`, `db.rollback`, or any other SQLAlchemy mutating method from the dispatcher.
- [x] 2.3 Do not modify `backend/llm/intent_classifier.py`, `backend/intents/orchestration/agregar_producto_orchestrator.py`, `backend/intents/orchestration/pending_context_dispatcher.py`, `backend/intents/schemas/intent_classification.py`, `backend/intents/schemas/processed_intent.py`, or `backend/models/session.py`.
- [x] 2.4 Do not import anything from `backend/old_project/`.
- [x] 2.5 Do not add logging, retry/backoff, caching, or async wrappers to the dispatcher.

## 3. Verification

- [x] 3.1 Add `backend/tests/test_initial_intent_dispatcher.py` with stubs: patch `IntentClassifier` at the dispatcher's import site and patch `process_initial_agregar_producto` with a `MagicMock` returning a sentinel `ProcessedIntent`. Use `unittest.TestCase` style consistent with `backend/tests/test_intent_classifier.py`.
- [x] 3.2 Cover `agregar_producto` invocation: classifier returns one `AGREGAR_PRODUCTO` item, the orchestrator mock is called exactly once with `classified.mensaje`, and the returned list contains the orchestrator's sentinel value unchanged.
- [x] 3.3 Cover multi-intent order preservation: classifier returns `[AGREGAR_PRODUCTO, DESCONOCIDA, SALUDO]` and the returned list preserves that order with the orchestrator mock in slot 0 and rejected `ProcessedIntent` items in slots 1 and 2.
- [x] 3.4 Cover `desconocida` rejection: classifier returns `DESCONOCIDA`, the orchestrator mock is NOT called, and the returned list contains one `ProcessedIntent(intent="desconocida", source_text=<classified.mensaje>, status="rejected", recognizer="intent_classifier", handler="desconocida")` with default-empty `resolved_data`, `requirements`, `candidate_ids`.
- [x] 3.5 Cover unsupported-intent rejection: classifier returns `SALUDO` and `QUITAR_PRODUCTO` separately; the orchestrator mock is NOT called and the rejected `ProcessedIntent` carries `handler=classified.intent.value` (i.e. `"saludo"` or `"quitar_producto"`).
- [x] 3.6 Cover the active-pending-context guard: `session.context_type == "product_selection"` returns `[]` and neither the classifier nor the orchestrator mock is invoked.
- [x] 3.7 Cover the `None` context pass-through: `session.context_type is None` proceeds past the guard and the classifier mock is consulted.
- [x] 3.8 Cover `db.commit`/`db.rollback` non-invocation: the dispatcher calls no commit/rollback method on the supplied `db` mock; assert `db.commit.assert_not_called()` and `db.rollback.assert_not_called()`.
- [x] 3.9 Run `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_initial_intent_dispatcher` and confirm all tests pass without a real LLM call, without a real `supernova_test` connection, and without any network access.
- [x] 3.10 Run `PYTHONPATH=. venv/bin/python -m compileall backend` and confirm exit 0.
- [x] 3.11 Run `openspec validate initial-intent-classification-integration-3-23 --strict` and confirm valid.

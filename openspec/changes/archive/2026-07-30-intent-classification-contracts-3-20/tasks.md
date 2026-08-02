## 1. Schema Implementation

- [x] 1.1 Inspect legacy `IntentClassifier` only to copy intent names verbatim; do not import or modify the legacy module.
- [x] 1.2 Create `backend/intents/schemas/intent_classification.py` with the aliased `IntentName` `StrEnum` and the `ClassifiedIntent` and `IntentClassificationResult` Pydantic models.
- [x] 1.3 Export `IntentName`, `ClassifiedIntent`, and `IntentClassificationResult` through `__all__` and keep the module free of LLM, prompt, HTTP, session, pedido, or context-mutation logic.

## 2. Verification

- [x] 2.1 Add schema tests for valid single-intent, valid multi-intent (order preserved), unsupported intent, missing/empty `mensaje`, empty `intents`, and extra fields.
- [x] 2.2 Run the focused schema tests and report results.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend`.

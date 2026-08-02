## Why

Subphase 3.20 delivered the typed intent-classification contracts and Subphase 3.21 delivered the reusable `QueryLlm` LLM client, but no implementation actually classifies a free-form client message into the legacy intent catalog. Subphase 3.22 ports and adapts the legacy `IntentClassifier` so the modern stack has a single, testable entry point that turns a raw message into an `IntentClassificationResult` without duplicating HTTP, payload, or logging logic already covered by `QueryLlm`.

## What Changes

- Add `backend/llm/intent_classifier.py` exporting `IntentClassifier` with `IntentClassifier(query_llm=None).query(message: str) -> IntentClassificationResult`.
- Preserve the legacy intent catalog and prompt instructions, correcting only invalid JSON examples, inconsistent intent names, and relevant spelling errors.
- Build the prompt without mutable `_message` or `_prompt` state.
- Delegate the LLM call to `QueryLlm.request(prompt)` and validate the returned dict with `IntentClassificationResult`.
- Reject empty / non-string messages and propagate `QueryLlmError` plus `pydantic.ValidationError` without printing or returning `None`.
- Use a module logger at `INFO` for start/success/failure and `DEBUG` for the validated classification only; do not configure global handlers and do not duplicate `QueryLlm` prompt/raw-response logs.
- Keep the module free of `Session`, `Pedido`, dispatcher, handler, recognizer, resolver, processor, FastAPI, and database code.
- Add focused unit tests in `backend/tests/test_intent_classifier.py` using a mocked `QueryLlm`.

## Capabilities

### New Capabilities
- `intent-classifier`: Defines the modern `IntentClassifier` consumer of `QueryLlm`, its prompt construction, validation contract, and logging boundaries.

### Modified Capabilities
- `intent-classification-contracts`: No requirement changes; remains the authoritative typed contract for `IntentName`, `ClassifiedIntent`, and `IntentClassificationResult`.

## Impact

- New module `backend/llm/intent_classifier.py` (sibling of `backend/llm/query_llm.py`).
- New tests `backend/tests/test_intent_classifier.py` (mocked `QueryLlm`; no real LLM call).
- Reused unchanged: `backend/llm/query_llm.py`, `backend/intents/schemas/intent_classification.py`, `backend/config/settings.py`.
- No changes to recognizer, resolver, processor, orchestrator, dispatcher, handler, services, pending-context, session, pedido, router, dependency, or migration code.
- Legacy `backend/old_project/intent_classifier.py` remains reference-only and is neither imported nor modified.
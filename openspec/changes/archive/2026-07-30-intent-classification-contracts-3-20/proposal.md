## Why

The legacy `IntentClassifier` defines a stable set of conversational intent names that downstream components and tests must continue to recognize, but the project currently lacks a Pydantic contract to enforce those names and the classification result shape. Subphase 3.20 introduces that contract module without implementing any classifier logic, ensuring future implementations share a single source of truth.

## What Changes

- Add `backend/intents/schemas/intent_classification.py` exporting `IntentName`, `ClassifiedIntent`, and `IntentClassificationResult`.
- Preserve the exact intent names and values currently declared in the legacy `IntentClassifier`.
- Define validation rules for the per-intent message and the aggregated result.
- Add schema-level tests covering the new contracts.
- Do not modify, import, or reuse the legacy `IntentClassifier` or `QueryLlm` modules.

## Capabilities

### New Capabilities
- `intent-classification-contracts`: Defines the Pydantic schemas for intent names, single-classified intents, and full classification results.

### Modified Capabilities

## Impact

- New file `backend/intents/schemas/intent_classification.py`.
- New schema tests in `backend/tests/api_smoke.py` or equivalent.
- No changes to recognizer, resolver, processor, orchestrator, dispatcher, handler, services, or pending context execution.
- No LLM, prompt, or HTTP integration changes.

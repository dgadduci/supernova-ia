## Context

The legacy `IntentClassifier` defines a stable set of conversational intent names that downstream components and tests must continue to recognize, but the project currently lacks a Pydantic contract to enforce those names and the classification result shape. This subphase introduces that contract module without implementing any classifier logic, ensuring future implementations share a single source of truth.

## Goals / Non-Goals

**Goals:**
- Provide a stable Pydantic schema for individual classified intents and the aggregated classification result.
- Preserve the exact intent names and values currently declared in the legacy `IntentClassifier`.
- Validate inputs (trim, reject empty, reject extra fields, require at least one intent).
- Add focused schema tests covering the contracts.

**Non-Goals:**
- Implementing any LLM call, prompt, or HTTP integration.
- Modifying or importing the legacy `IntentClassifier` or `QueryLlm` modules.
- Touching recognizer, resolver, processor, dispatcher, handler, services, or pending context execution.

## Decisions

- Use `StrEnum` for `IntentName` so the values match the legacy names exactly while preserving Python typing guarantees.
- Place the contracts in `backend/intents/schemas/intent_classification.py` to align with the existing intent schema package and avoid new dependencies.
- Make `mensaje` an empty-after-trim-rejecting string on both `ClassifiedIntent` and `IntentClassificationResult` so callers cannot accidentally store blank inputs.
- Require `IntentClassificationResult.intents` to contain at least one entry and to preserve the order produced by the classifier, mirroring the legacy order-preservation rule.
- Reject extra fields on both schemas to keep the contract minimal and predictable.
- Export public symbols through `__all__` so the module exposes the same surface as the existing intent schema modules.

## Risks / Trade-offs

- [Risk] `IntentName` drift if the legacy classifier is renamed later → Mitigation: copy values verbatim and document that changes must happen in a dedicated subphase.
- [Risk] Empty-message attacks via trimmed whitespace → Mitigation: schema-level rejection of empty-after-trim values.
- [Risk] Future types become more complex and require nested data → Mitigation: keep the current contract minimal and document that richer variants are deferred to a future subphase.

## Migration Plan

1. Read the legacy `IntentClassifier` source only to copy intent names verbatim.
2. Add the new schema module with `__all__`.
3. Add focused tests covering the minimum scenarios.
4. Run the schema tests and the compile check; rollback by deleting the module and its tests if needed.
5. Leave recognizer, resolver, processor, and dispatcher untouched.

## Open Questions

None.

## Why

The pending `PRODUCT_SELECTION` flow can present the customer with a numbered list of candidates (e.g. `1. Coca-Cola Lata`, `2. Coca-Cola Zero Lata`), but the current `product_selection_context_resolver` only recognises presentacion aliases (e.g. `grande`) and the existing discriminating-fragment path (e.g. `picante`). It does not interpret numeric, positional, exact-name, token-set, default-variant (`común`, `normal`, `regular`, `original`), or explicit-exclusion (`la que no es zero`) replies, so a clear customer reply such as `1`, `primera`, `coca cola en lata`, or `la que no es zero` is left ambiguous and the conversation stalls. The change adds a narrow, candidate-scoped, reusable resolver that closes these gaps without changing embeddings, hybrid scoring, calibration, or the general recognizer.

## What Changes

- New pure resolver module `backend/intents/context/pending_product_ambiguity_resolver.py` exporting `resolve_pending_product_ambiguity` through `__all__`. It applies a deterministic 9-layer resolution order against the persisted active `candidate_ids` and their catalog projection; it never queries the full commerce catalog and never loads candidates outside the active intent's `candidate_ids`.
- Extend the existing `ProductSelectionContextService.resolve` orchestration to invoke the new resolver as a sibling step after the existing fragment-based resolution. When the existing path leaves the intent unchanged (no presentacion alias and no fragment match), the new resolver is consulted. When either path resolves uniquely, the new resolver is skipped.
- New focused pytest module `backend/tests/test_pending_product_ambiguity_resolution.py` covering each resolution layer in isolation (numeric, positional, exact-name, token-set, differentiating-token, contextual default, explicit negation, restricted fuzzy fallback, ambiguous remain) plus an end-to-end conversation integration test reproducing the Coca-Cola Common vs Zero exchange. The existing pending-context and end-to-end suites remain green.
- New capability spec `openspec/specs/pending-product-ambiguity-resolution/spec.md` documenting the 9-layer contract, the candidate-scope invariant, the Coca-Cola Common vs Zero + a second generic family example, and the explicit non-goals (no embeddings, no hybrid activation, no catalog mutations, no global aliases).
- Modified capability spec delta `openspec/specs/product-selection-context-orchestration/spec.md` adding the integration scenario that exercises the new resolver through `ProductSelectionContextService.resolve` without altering existing behaviour.

## Capabilities

### New Capabilities
- `pending-product-ambiguity-resolution`: narrow, pure, candidate-scoped resolver that closes the nine resolution layers (`1.` numeric, `2.` positional, `3.` exact normalized full-name, `4.` exact token-set after filler stripping with subset preference and distinguishing-token penalty, `5.` differentiating-token, `6.` contextual default descriptors, `7.` explicit negation, `8.` restricted fuzzy fallback over candidates, `9.` remain ambiguous) for `pending_resolution` `agregar_producto` intents whose `candidate_ids` is non-empty.

### Modified Capabilities
- `product-selection-context-orchestration`: extend `ProductSelectionContextService.resolve` to consult the new resolver when the existing fragment path leaves the intent unchanged; existing behaviour and existing scenarios are preserved verbatim. No changes to `product-selection-context-resolver`, `pending-context-dispatcher`, `pending-context-execution`, handlers, response builders, or transactions.

## Impact

- `backend/intents/context/pending_product_ambiguity_resolver.py` (new) — pure resolver.
- `backend/intents/context/product_selection_context_service.py` (modify) — invoke the new resolver as a sibling step.
- `backend/tests/test_pending_product_ambiguity_resolution.py` (new) — focused unit tests + Coca-Cola Common vs Zero integration test.
- `openspec/specs/pending-product-ambiguity-resolution/spec.md` (new capability).
- `openspec/specs/product-selection-context-orchestration/spec.md` (delta: add integration scenario).
- No SQLAlchemy schema change, no Alembic migration, no FastAPI endpoint, no handler, no response builder, no recognizer change, no embeddings, no hybrid mode activation, no calibration dataset/policy change, no global alias table change.

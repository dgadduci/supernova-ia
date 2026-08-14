# Design: product-modification pending destination selection

## Decision

Add one narrow pre-check inside `_resolve_destination_selection`, after its
existing restricted destination catalog is loaded and before it calls
`detectar_productos`.

```text
active destination_candidate_ids
  -> existing list_presentaciones_by_ids(ids)
  -> normalize reply; exact bare code / one leading article only
  -> exactly one matching restricted presentation
       -> existing _build_ready_intent -> existing execution
  -> otherwise existing detectar_productos + intersection fallback
```

The pre-check compares the project's normalized incoming text to the
normalized `presentacion_codigo` already returned by the restricted catalog.
It accepts one token, or two tokens where the first is one permitted Spanish
article (`la`, `el`, `una`, `un`, `las`, `los`). It does not strip a product
name, accept partial/fuzzy aliases, compare descriptions, or search any
catalog beyond the persisted candidate IDs.

## Ownership and failure behavior

- Exactly one match reuses `_build_ready_intent`; the resolver does not invoke
  `detectar_productos`, hybrid/vector/LLM, a handler, or transaction control
  for that decision.
- Zero or multiple matches invoke the current recognizer/intersection path
  unchanged. The fallback is responsible for full product replies and all
  other natural language.
- The source candidate list is preserved exactly. This change neither chooses
  a source nor alters `cantidad`.
- Existing service read exceptions and existing invalid/missing-source
  outcomes retain their present behavior. No exception is swallowed to turn a
  technical failure into a selection.

## Panel projection

The panel remains a closed, no-PII view. It adds `modificar_producto` to the
already-existing active-intent allowlist. Its candidate count derives only a
number: for a valid active modification it counts
`resolved_data.destination_candidate_ids` at `destination_selection` and
`resolved_data.source_candidate_ids` at `source_selection`; all other intents
retain their current `candidate_ids` count. This lets a valid pending
modification display `consistent` without exposing any candidate value.

## Tests

- Resolver tests cover exact `chica`, case/article variation, one matching
  restricted destination, no recognizer call on deterministic success,
  preserved source/quantity and no transaction methods.
- Zero/multiple/foreign/multi-token replies use the existing recognizer
  fallback and never widen the destination list.
- A focused pending-to-execution proof performs destination clarification
  then `chica`, moving exactly the requested quantity and clearing pending.
- Panel tests assert the permitted active intent, stage-specific count,
  consistent value, no raw payload leakage, invalid-state behavior unchanged
  and no session mutation.

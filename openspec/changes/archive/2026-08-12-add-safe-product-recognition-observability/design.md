# Design: safe product-recognition decision observability

## Decision

Extend the existing `backend.observability.events` schema rather than parsing
the recorder's Python log extras. `ShadowMetricsRecorder` will emit exactly one
catalogued structured event per existing observation through the shared
emitter. This makes the current bounded Railway CLI usable without a parallel
log format or raw-log escape hatch.

## Safe event contract

The event name remains `shadow_product_recognition`, with component
`product_recognition`. It carries the standard version/timestamp envelope and
only these recognition fields:

- `configured_mode` and `effective_mode`: `fuzzy`, `shadow`,
  `hybrid_authoritative`, or a sanitized configured-invalid category;
- `authoritative_strategy`: `fuzzy` or `hybrid`;
- `hybrid_decision`: `unique`, `ambiguous`, `unknown`, or a documented
  unavailable category only when hybrid evaluation did not complete;
- `fallback`: boolean;
- `fallback_category`: absent unless fallback is true, restricted to existing
  sanitized technical categories plus `invalid_mode`;
- `fuzzy_latency_ms`, `embedding_latency_ms` and `vector_latency_ms`: bounded
  non-negative integer durations when available.

The schema rejects every other key. In particular, it forbids `id_comercio`,
intent/correlation values, result IDs, candidate counts/rankings, scores,
exact-match flags, policy values, messages and exception strings. The event
does not need an `outcome`/`failure_category` pair: the recognition fields
above are its closed event-specific observation shape.

## Behavior

The recorder maps its already-computed values to the event without changing
recognition work. `unique`, `ambiguous` and `unknown` are valid business
observations whether the mode is shadow or hybrid-authoritative. A fallback is
true only for the existing technical categories; an unavailable vector or
business ambiguity must not manufacture a fallback. Invalid configured mode
continues resolving to effective fuzzy, recorded only with the sanitized
`invalid_mode` category.

The CLI remains unchanged at its public boundary: it obtains a bounded Railway
JSON window, strips the known Railway envelope, validates each event through
the catalogue and applies local filters. Its output is the validated safe
event only. Unknown fields or malformed claimed events remain a safe parsing
failure; they are never printed raw.

## Transactions, failure and rollback

Neither the recorder nor the shared emitter accesses a session or changes
commit/rollback ownership. Emission failure is swallowed by the existing
observability boundary and must not block a recognition result. Removing the
recorder-to-emitter integration rolls back the change without data migration
or Railway mutation.

## Tests

Focused tests prove allowed fuzzy/shadow/hybrid events round-trip through the
catalogue and CLI; technical fallback is valid; business `unknown` and
`ambiguous` do not become fallback; forbidden fields are rejected; recorder
emission has no transaction or recognition side effects; and malformed Railway
event claims never leak raw lines.

# Design: order-line size-only pending selection

## Decision

Add a narrow deterministic pre-check inside `resolve_order_line_selection`.
It is active only for a `quitar_producto` intent in `pending_resolution` with
candidate IDs.

```text
active candidate_ids
  -> existing session.id_pedido line read
  -> filter to candidate IDs
  -> normalize reply and presentacion.codigo
  -> exactly one match: existing _build_ready_intent
  -> otherwise: existing recognize_quitar_producto + intersection behavior
```

## Exact matching contract

Use the project's existing normalization. Compare only
`presentacion.codigo`, which is the value rendered to the customer. Accept the
exact normalized code, with at most one leading article removed (`la`, `el`,
`una`, `un`, `las`, `los`). No other token is ignored.

The helper returns an ID only for exactly one current candidate. It returns no
result for zero/multiple matches, unsupported intent, missing `id_pedido`,
empty text or malformed relation. In every such case the existing recognizer
path remains the fallback. `Napolitana chica` is not bare and does not bypass
the existing candidate intersection.

## Ownership and safety

The deterministic success path calls neither `recognize_quitar_producto` nor
the hybrid/LLM boundary. It reuses `_build_ready_intent`, preserving original
requirements and resolved data. The pending dispatcher still stages the
result; existing ready execution still calls the handler and clears
pending/context. The resolver owns no transaction method and performs no
direct ORM query or catalog fallback.

## Tests

- `Chica`, case variation, `la chica`, and `Grande` select only the matching
  restricted candidate; they do not call the recognizer or transaction APIs.
- Outside product phrase, no match, duplicate code and unsupported intent use
  the existing fallback without candidate widening.
- A focused dispatch/handler proof removes only the selected own line and
  clears the context through existing execution and response mapping.

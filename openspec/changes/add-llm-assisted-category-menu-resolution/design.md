# Design: bounded category resolution for `ver_menu`

## Decision

Do not change `IntentClassificationResult`, add an intent, or pass dynamic
catalog data into the primary classifier. Reuse the existing primary
classification (`ver_menu`) and issue one dedicated, typed LLM call only in
the read-only menu branch. This isolates dynamic catalog context and avoids a
global classification-schema change.

## Candidate construction

`_resolve_menu` already obtains the current commerce's sellable products in
configured order. It shall derive one candidate per category which has at
least one sellable presentation in that same result. Internally, a candidate
contains the real category identity. Its LLM projection contains only:

```json
{"token": "c1", "nombre": "Empanadas"}
```

Tokens are assigned in this invocation's configured category order and are
opaque: they are not database IDs and are not persisted. The list is bounded
to at most 20 candidates, each name at most 80 characters, with a total
serialized category-context ceiling of 2,000 characters. If the candidate
set cannot be represented inside these bounds, the resolver is skipped and
the existing full menu is rendered.

## Dedicated resolver contract

The resolver uses the existing configured LLM transport but owns its own
static prompt template, version and fingerprint. Its runtime prompt contains:

- the classified `ver_menu` source text;
- the bounded list of opaque `(token, nombre)` candidates; and
- a request for JSON with either one exact candidate pair or null selection.

The schema is closed (`extra="forbid"`). A selection requires both `token` and
`nombre`; a no-selection requires both to be null. The prompt says to return
null when none or more than one category is justified, and never to invent or
transform tokens/names. The model never receives a category database ID.

The resolver may help with natural wording, singular/plural and minor spelling
variation. It does not authorize catalog access: the orchestration validates
the pair against the candidate list by exact token AND exact name. It then
uses only the backend-held category identity to filter the already-loaded
products. A valid but semantically mistaken existing candidate remains
possible with any language model; the resulting response explicitly names the
chosen category, while null/failure preserves the complete menu rather than
guessing a new category.

Before the secondary call, the orchestration applies one conservative,
deterministic ambiguity guard to the already-built current-commerce candidate
names. If the normalized source text explicitly identifies two or more
distinct visible category names, it skips the resolver and preserves the full
menu. This guard does not resolve a single category, add aliases, perform
fuzzy/vector search, or change the candidate set; it only prevents an explicit
multi-category request from being narrowed by the LLM.

## Execution sequence

```text
pending dispatcher (unchanged priority)
  → primary IntentClassifier (unchanged one call)
  → ver_menu informational orchestration
  → list_vendibles(session.id_comercio) once
  → no items: existing no_items
  → bounded category candidate projection
  → explicit multi-category guard: full menu, no second call
  → dedicated category resolver once
  → exact token + name validation
  → filter in-memory vendible result by backend identity OR full-menu fallback
  → existing shared response mapper/outbox/local rendering
```

The first classification prompt gets static category-browse guidance only; it
does not get category names. The second resolver is never called for another
intent, pending turn, empty catalog, oversized category context, or a product
detail query.

## Rendering

For a valid selected category, `resolved_data` contains the filtered current
menu items and the exact category display name needed for a deterministic
heading such as `Empanadas disponibles:`. It does not retain candidate token,
real category ID, raw LLM result or raw prompt. The existing full-menu
`resolved_data` and response text remain byte-for-byte compatible when the
resolver yields no selection or fails.

## Failure and transaction handling

The resolver catches its documented transport and response/schema failures at
its boundary and returns typed no-selection with a closed failure class; it
does not leak exception text or cause the caller-owned order transaction to
roll back. It owns no transaction methods. The informational orchestration
does not write or retry. The primary classifier's existing behavior and its
transaction ownership remain unchanged.

## Tests

- Primary static prompt/corpus classifies category browsing as `ver_menu` and
  preserves concrete product detail as `consultar_producto`, including the
  pilot wording `qué gustos de empanadas tenés`, `qué gustos de empanadas hay`
  and `qué bebidas tenés`; prompt version and static fingerprint change
  intentionally without incorporating customer text.
- Dedicated resolver tests cover valid pair, null, malformed/extra output,
  token-name mismatch, unknown token/name, candidate bounds, prompt privacy,
  and no raw text/category/ID diagnostics.
- Informational-query tests cover Pizzas/Empanadas/Bebidas filtering, one
  `list_vendibles` call, current-commerce isolation, no second resolver for
  non-menu/pending/no-items/oversize/explicit-multi-category cases, and
  full-menu fallback on every invalid or technical resolver outcome.
- Response tests cover selected-category heading and unchanged full-menu
  rendering fallback.

# Design: hybrid product quantity preservation

## Decision

Keep hybrid authoritative product selection unchanged and repair only the
translation payload. Before constructing a `RecognizedProduct`, use the
existing deterministic quantity extractor from the shared product-recognizer
module against the original input text. Pass that positive integer into the
translator instead of hard-coding one for a unique result or omitting it for
an ambiguous candidate.

```text
"quiero dos napolitanas grandes"
  -> existing fuzzy parser: quantity 2
  -> existing hybrid ranking: selected in-catalog presentation
  -> translator: selected presentation, or each bounded candidate, + quantity 2
  -> existing resolver persists 2; existing add seam adds 2 after selection
```

The extractor is not a semantic authority and does not consult a catalog,
embedding, vector result, LLM or database. It therefore cannot change the
unique candidate, expand an ambiguous candidate set, alter a hybrid decision,
or infer a quantity from the later customer selection reply.

## Boundaries and failure behavior

- The selected product id remains `ranking[0]` from the existing filtered
  hybrid ranking. No quantity path may change it.
- For an ambiguous decision, the existing filtered ranking remains exactly the
  group of candidate ids. The same parsed quantity is only attached to each
  already-selected candidate so `resolve_product_intent` can retain it in the
  existing pending state.
- Omitted quantities retain the extractor's existing default of `1`.
- Ambiguous and unknown translations keep their existing output shapes and do
  not become unique based on a quantity. An ambiguous result never chooses a
  candidate before the customer reply.
- Infrastructure fallback returns the original fuzzy result unchanged, so no
  new parsing is applied on that branch.
- Existing response mapping receives the corrected `cantidad_final` only after
  the current resolver/handler/seam path; no response or panel calculation is
  introduced.
- The recognizer remains pure and transaction-free.

## Tests

- Unit coverage of hybrid `unique` translations for explicit word quantities
  two and three, an omitted quantity default, exact candidate bounds and no
  policy/ranking regression.
- Unit coverage that `ambiguous` translation of `dos empanadas de carne`
  keeps the same candidate ids/order while every candidate carries `cantidad`
  two; omitted quantity carries one.
- Pending-selection coverage showing that the existing resolver persists two
  before a bounded `picante`/`suave` reply and that the reply does not replace
  it with one.
- Technical fallback returns the fuzzy result object/value including its
  supplied quantity.
- Route-level regression injects a real configured
  `HybridAuthoritativeProductRecognizer` with deterministic classifier,
  embedding and vector collaborators, but does not mock the product recognition
  function, resolver, handler, repository, transactional processor, response
  mapper or order-lines snapshot. It proves raw text quantities `1`, `2`, `3`
  yield response/snapshot/durable totals `1`, `3`, `6`; add the same real
  route coverage for ambiguous Carne selection with a requested quantity two.

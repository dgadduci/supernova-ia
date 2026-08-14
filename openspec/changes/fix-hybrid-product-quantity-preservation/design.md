# Design: hybrid product quantity preservation

## Decision

Keep hybrid authoritative product selection unchanged and repair only the
translation payload for a `unique` decision. Before constructing the
`RecognizedProduct`, use the existing deterministic quantity extractor from
the shared product-recognizer module against the input text. Pass the resulting
positive integer into the translator instead of hard-coding one.

```text
"quiero dos napolitanas grandes"
  -> existing fuzzy parser: quantity 2
  -> existing hybrid ranking: selected in-catalog presentation
  -> translator: selected presentation + deterministic quantity 2
  -> existing resolver and add seam: add 2
```

The extractor is not a semantic authority and does not consult a catalog,
embedding, vector result, LLM or database. It therefore cannot change the
unique candidate, expand a candidate set, or alter a hybrid decision.

## Boundaries and failure behavior

- The selected product id remains `ranking[0]` from the existing filtered
  hybrid ranking. No quantity path may change it.
- Omitted quantities retain the extractor's existing default of `1`.
- Ambiguous and unknown translations keep their existing output shapes and do
  not become unique based on a quantity.
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
- Technical fallback returns the fuzzy result object/value including its
  supplied quantity.
- Route-level regression injects a real configured
  `HybridAuthoritativeProductRecognizer` with deterministic classifier,
  embedding and vector collaborators, but does not mock the product recognition
  function, resolver, handler, repository, transactional processor, response
  mapper or order-lines snapshot. It proves raw text quantities `1`, `2`, `3`
  yield response/snapshot/durable totals `1`, `3`, `6`.

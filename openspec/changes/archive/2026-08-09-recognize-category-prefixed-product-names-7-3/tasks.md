## 1. Fuzzy recognizer refinement

- [x] 1.1 Refine the existing key-token filter so a candidate-compatible
  category token is context only when at least one product token remains.
- [x] 1.2 Preserve current extraction, scoring, aliases, quantities,
  presentation narrowing, availability and category-only fallback behavior.

## 2. Focused regression coverage

- [x] 2.1 Add the exact `3 Pizza napolitana` regression for product name
  `Napolitana` in category `Pizzas`, asserting only scoped candidates and
  quantity `3`.
- [x] 2.2 Cover category-only and incompatible-category non-promotion, plus
  an existing prefixed-product-name regression.
- [x] 2.3 Run and report every validation command from `proposal.md`.

## 3. Boundary

- [x] 3.1 Do not modify catalog fixture data, aliases, hybrid/vector policy,
  provider/inbound/outbox flow, schema, migrations, configuration, deploy,
  commit, sync or archive.

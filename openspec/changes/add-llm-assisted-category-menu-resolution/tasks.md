## 1. Bounded category resolver

- [x] 1.1 Add a dedicated typed resolver and versioned static prompt that
  accepts only raw menu query plus bounded opaque category token/name pairs.
- [x] 1.2 Return a strict selected pair or no-selection; contain documented
  transport/schema failures as typed no-selection without raw-text/ID/error
  leakage or transaction ownership.

## 2. `ver_menu` integration

- [x] 2.1 Reuse the existing one-call sellable catalog load to build current-
  commerce category candidates, invoke the resolver only for `ver_menu`, and
  validate token and name exactly before filtering by backend-held identity.
- [x] 2.2 Render a selected-category heading and items; preserve exact current
  full-menu behavior for null, invalid, oversized, empty or failed resolution.
- [x] 2.3 Add static primary-classifier prompt/corpus guidance distinguishing
  category browsing (`ver_menu`) from concrete product detail
  (`consultar_producto`), including the pilot category-browse wording, and
  update static template identity/version.
- [x] 2.4 Add a bounded, read-only explicit multi-category guard based only on
  the current candidate names. It must preserve the full menu and skip the
  second resolver for two or more explicit category references; it must not
  select a category, add aliases, or use fuzzy/vector matching.

## 3. Focused proof and validation

- [x] 3.1 Add focused resolver/orchestration/response/classifier tests for
  Pizzas, Empanadas and Bebidas; token/name mismatch; invalid/null/failure
  fallback; bounds; privacy; commerce isolation; one catalog read; explicit
  multi-category fallback without a resolver call; no pending bypass; and no
  mutation/transaction controls.
- [x] 3.2 Run every focused pytest, Ruff, compileall, strict OpenSpec
  validation and `git diff --check` command in `proposal.md`.

## 4. Pilot gate

- [ ] 4.1 After approved deploy, use the pilot to verify a category phrase,
  varied wording, unavailable/unknown category fallback, and unchanged
  concrete-product detail behavior; request explicit approval before archive.

# Tasks

## 1. Exact normalization

- [x] 1.1 Add only the approved `grandes` and `chicas` presentation plural
  mappings before generic singularization.
- [x] 1.2 Preserve existing normalization ordering, fuzzy/hybrid policy,
  catalog isolation and transaction ownership.

## 2. Focused proof

- [x] 2.1 Test plural Grande/Chica recognition, exact presentation filtering,
  quantity `2`, singular regressions and absent/ambiguous behavior.
- [x] 2.2 Add the smallest add-product execution proof that a plural Grande
  request reaches the existing quantity-two increment seam without new
  transaction control.
- [x] 2.3 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report complete output and pre-existing failures.

## 3. Production gate

- [ ] 3.1 After approved deploy, repeat `quiero dos napolitanas grandes` on
  the current active draft; verify quantity changes from 1 to 3, one success
  response and empty pending/context.
- [ ] 3.2 Resume the product-flow TODO only after 3.1; do not archive without
  explicit user approval.

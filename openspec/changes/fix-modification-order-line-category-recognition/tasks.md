# Tasks
## 1. Owned category projection

- [x] 1.1 Project the existing eager-loaded category description as
  `categoria_nombre` in `modificar_producto`'s source order-line catalog;
  add no query or candidate source.
- [x] 1.2 Preserve source identity projection and all zero/one/many candidate
  behaviors without changing destination or quantity paths.

## 2. Focused proof

- [x] 2.1 Cover Pizza/Mozzarella and Empanadas/Verdura category-qualified
  source recognition, including exact own-order-line IDs and no widening.
- [x] 2.2 Cover category-qualified source ambiguity, absent-own-source safe
  rejection, and the smallest initial/end-to-end no-mutation boundary.
- [x] 2.3 Run focused pytest, Ruff, compileall, strict OpenSpec validation,
  and `git diff --check`; report pre-existing failures separately.

## 3. Pilot gate

- [x] 3.1 After approved deploy, test the two reported category-qualified
  messages against known draft lines and verify the existing success/pending
  result, exact lines, and cleared context when executed.
- [x] 3.2 Test an outside-draft category-qualified source remains rejected
  with no line mutation; complete the quantity-spec regression gates before
  archiving either change, and archive only with explicit user approval.

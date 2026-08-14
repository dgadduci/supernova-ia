# Tasks

## 1. Restore source-line identity

- [x] 1.1 Add a private source-result projection in
  `modificar_producto_recognizer` that maps only exact current source-catalog
  presentation IDs back to their own `pedido_producto_id` values.
- [x] 1.2 Apply it to unique and ordinary possible source entries while
  preserving category groups, destination recognition, quantity, ranking,
  fallback and no-transaction behavior.

## 2. Focused proof

- [x] 2.1 Cover hybrid-shaped unique and ambiguous source results that carry
  no line ID, plus foreign/unmapped/category/malformed results and strict
  source/destination separation.
- [x] 2.2 Add the smallest real-hybrid modification integration proof for
  `cambiar 2 napolitanas grandes por 2 napolitanas chicas`, asserting the
  exact two-unit transfer, own-line isolation and context cleanup.
- [x] 2.3 Preserve no-mutation rejection and caller-owned transaction tests.
- [x] 2.4 Run the focused pytest, Ruff, compileall, strict OpenSpec validation
  and `git diff --check`; report complete output and pre-existing failures.

## 3. Pilot gate

- [ ] 3.1 After approved deploy, use the local pilot channel to change two
  Napolitana Grande to two Napolitana Chica; verify both durable quantities,
  response, own-order isolation and empty pending/context.
- [ ] 3.2 Resume the product-flow TODO and consider archive only after 3.1
  succeeds and explicit user approval is given.

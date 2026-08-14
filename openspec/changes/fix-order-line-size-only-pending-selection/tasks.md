# Tasks

## 1. Deterministic restricted refinement

- [x] 1.1 Add exact bare-presentation normalization and candidate-only lookup
  in `order_line_selection_resolver`, only for pending `quitar_producto`.
- [x] 1.2 Route one unique match through the existing ready helper without
  product/hybrid/LLM recognition; retain existing fallback otherwise.

## 2. Focused proof

- [x] 2.1 Cover Chica/Grande, candidate restriction, preserved data, no
  recognizer call on deterministic success, and no transaction methods.
- [x] 2.2 Cover outside phrase, no-match, duplicate code and unsupported
  intent; prove no candidate widening.
- [x] 2.3 Add the smallest dispatcher/handler proof that the chosen own line
  alone changes and existing execution clears pending/context.
- [x] 2.4 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report complete output and pre-existing failures.

## 3. Controlled validation gate

- **Deferred by explicit user decision (2026-08-14):** only one pilot client
  is currently available, so independent clean drafts for the separate
  `Chica` and `Grande` runs cannot be provisioned safely. Keep this gate
  unchecked; it is not a passed production validation and must be resumed
  when an isolated client/draft setup is available.
- [ ] 3.1 After approved deploy, use clean panel-local drafts to test Chica
  and Grande separately; verify only selected line change and context cleanup.
- [ ] 3.2 Resume WhatsApp gates only after 3.1; do not archive without
  explicit user approval.

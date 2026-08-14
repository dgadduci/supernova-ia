# Tasks

## 1. Prompt contract

- [x] 1.1 Add semantic removal guidance and concise representative examples
  (`saca`/`sacar`, `retirá`/`retirar`, `eliminá`/`eliminar`) mapping to
  `quitar_producto`; preserve unrelated intents without making a closed verb
  list or a second classifier.
- [x] 1.2 Bump the static prompt-template version and preserve the static-only
  fingerprint/privacy contract.

## 2. Focused proof

- [x] 2.1 Cover prompt rule/examples, message preservation, and controlled
  classifier schema for the reported and representative removal forms.
- [x] 2.2 Cover dispatcher routing of `QUITAR_PRODUCTO` only to the existing
  remove orchestrator; add must not run.
- [x] 2.3 Run focused pytest, Ruff, compileall, strict OpenSpec validation,
  and `git diff --check`.

## 3. Pilot gate

- [x] 3.1 Send `saca una de mozzarella chica` against an own line; verify
  decrement, no add, and cleared context/pending.
- [x] 3.2 Send `sacar dos de mozzarella chica`; verify existing remove
  semantics, no add, no unrelated mutation, and cleared context/pending.
- [x] 3.3 Send `retirá una de mozzarella chica`; verify removal rather than
  add, no unrelated mutation, and cleared context/pending.

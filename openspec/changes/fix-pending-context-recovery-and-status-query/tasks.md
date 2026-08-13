# Tasks

## 1. Pending recovery and read-only interruption

- [ ] 1.1 Add the closed deterministic status predicate and route it before a
  supported pending resolver, preserving pending state exactly.
- [ ] 1.2 Clear active pending state and `context_type` on a definitive
  resolver-produced rejection; preserve `pending_resolution` and technical
  failure behavior.
- [ ] 1.3 Align the static status classifier wording and controlled corpus for
  the normal no-context path.

## 2. Privacy-safe structured tracing

- [ ] 2.1 Extend the existing operational event catalogue and public exports
  with the closed `pending_context_transition` contract only.
- [ ] 2.2 Emit allowlisted transition events without PII and make emission
  failure observational only.

## 3. Focused verification

- [ ] 3.1 Add end-to-end coverage for Mozzarella ambiguity → `Grande` → add,
  rejected-context cleanup, and status during/after pending context.
- [ ] 3.2 Add predicate, prompt/corpus, event privacy/parse and bounded query
  CLI tests.
- [ ] 3.3 Run every focused pytest, Ruff, compileall, and strict OpenSpec
  validation command from `proposal.md` locally; report complete output.

## 4. Production gate and dependent change

- [ ] 4.1 After review and approved deployment, run the three controlled
  WhatsApp message sequences in `proposal.md`; record only outcomes and
  timestamps, never customer content or identifiers.
- [ ] 4.2 Resume `implement-product-line-observation-intent` only after 4.1
  succeeds; test it in production with messages.
- [ ] 4.3 Obtain explicit user approval before archiving the observation
  change. Do not archive this change as an implied consequence of its tests.

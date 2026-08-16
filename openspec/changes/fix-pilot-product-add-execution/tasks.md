# Tasks

## 1. Caller-owned product add

- [x] 1.1 Add the session-owned caller-transaction create/increment seam and
  typed business outcomes; leave legacy public methods unchanged.
- [x] 1.2 Route only modern `agregar_producto` through it and preserve current
  customer response mapping.

## 2. Safe operations diagnostics

- [x] 2.1 Add the bounded read-only commerce catalog price-availability view.
- [x] 2.2 Register and emit closed `product_add_execution` through the
  existing catalogue and query path.

## 3. Focused verification

- [x] 3.1 Add service/handler transaction and no-mutation tests.
- [x] 3.2 Add provider-coordinator ambiguity → `Grande` E2E tests for
  price-present and price-unavailable outcomes.
- [x] 3.3 Add panel authorization/isolation/no-mutation and event privacy/
  allowlist tests.
- [x] 3.4 Run every focused pytest, Ruff, compileall and strict OpenSpec
  validation command from `proposal.md`; report complete output.

## 4. Production gate and dependent changes

- [x] 4.1 After approved deploy, check Mozzarella Grande price availability in
  the panel. If unavailable, stop for separately approved catalog remediation.
- [x] 4.2 If available, run WhatsApp ambiguity → `Grande` and verify one line
  and success response in the panel.
- [x] 4.3 Resume the three production checks of
  `fix-pending-context-recovery-and-status-query` only after 4.2 succeeds.
- [ ] 4.4 Resume `implement-product-line-observation-intent` only after 4.3;
  do not archive any change without explicit user approval.

## 5. Sequential add quantity regression amendment

- [x] 5.1 Add a real sequential regression test for one exact presentation
  and one active draft: quantities `1`, `2`, `3` produce one durable line at
  `1`, `3`, `6`, with corresponding final-quantity responses.
- [ ] 5.2 Diagnose and correct only the smallest modern add seam, exact-line
  lookup, transaction-boundary or snapshot defect revealed by 5.1; preserve
  caller-owned transaction control and legacy add behavior.
- [x] 5.3 Prove the local-test JSON snapshot and panel update render the
  durable total (`6`), not a request delta or browser-local calculation.
- [x] 5.4 Run the focused validation commands added by this amendment and
  report complete output, distinguishing reproducible pre-existing failures.
- [x] 5.5 After approved deploy, replay quantities `1`, `2`, `3` in the pilot
  for the same draft/presentation; verify one line at `6`, responses with
  totals `1`, `3`, `6`, and empty pending/context. Resume the product-flow
  TODO only after this gate; do not archive without explicit approval.

## 6. Added Quantity Versus Total Wording Amendment

- [x] 6.1 Change only the deterministic executed add response to use
  `cantidad_agregada` as the customer-visible delta and `cantidad_final` as a
  separate resulting-total clause when they differ; retain legacy final-only
  compatibility and existing malformed fallback.
- [x] 6.2 Add focused created/incremented singular/plural, one-to-seven,
  legacy-final-only, invalid-data, pure-rendering, and no-transaction tests.
- [x] 6.3 Run the focused pytest, Ruff, compileall, strict OpenSpec validation,
  and `git diff --check` commands from `proposal.md`.
- [ ] 6.4 After approved deploy, add one known presentation to a line at six
  and verify the response states one added and seven total while the panel
  shows the same durable line total.

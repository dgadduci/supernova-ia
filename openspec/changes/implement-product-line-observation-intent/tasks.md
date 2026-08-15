# Tasks

## 1. Contract and caller-owned persistence seam

- [ ] 1.1 Add the product-line observation recognizer/orchestrator contract,
  including deterministic set/clear grammar and the `ProcessedIntent` data
  shape.
- [ ] 1.2 Add a repository/service operation that validates active-session
  ownership, draft state and line membership, writes a nullable observation,
  and has no transaction-control calls.

## 2. Runtime path

- [ ] 2.1 Add the order-line-only recognizer and initial orchestrator; route
  unique candidates to the handler and persist only ambiguous candidates.
- [ ] 2.2 Add the guarded handler, preserving `session.id_pedido` and active
  session validation, with deterministic business rejections and technical
  failure propagation.
- [ ] 2.3 Add the minimal branches in initial dispatch, context type, ready
  pending execution and the response mapper. Reuse existing
  `order_line_selection` refinement without candidate widening.
- [ ] 2.4 Add a deterministic, privacy-safe response builder.

## 3. Verification

- [ ] 3.1 Add focused unit/integration tests for set, clear, ambiguity,
  ownership, draft state, transaction ownership, response privacy, mapper
  routing and rollback behavior.
- [ ] 3.2 Run the focused pytest, Ruff, compileall and strict OpenSpec
  validation commands in `proposal.md` locally and report the complete output.

## 4. Explicitly deferred

- [ ] 4.1 Do not broaden natural-language clear extraction, add pedido-level
  observations, alter legacy service transaction behavior, change the
  classifier/prompt, or touch temporal-delivery scheduling.

## 5. Mandatory production gate before archive

- [ ] 5.1 PAUSED — wait for `add-pilot-order-operations-panel`, then for
  `fix-pending-context-recovery-and-status-query` to be
  completed, reviewed, deployed, and verified with real WhatsApp messages.
- [ ] 5.2 Resume this change only then; run its own production-message test
  against a controlled draft pedido and record the result without customer
  content or identifiers.
- [ ] 5.3 Request explicit user approval before archiving this change. Passing
  focused tests or merging code is not archive authorization.

## 6. Regression amendment: declarative observation classification

- [x] 6.1 Add only static prompt/corpus guidance for declarative,
  product-specific observations without an add verb; bump their versions.
- [x] 6.2 Add focused classifier and dispatcher coverage for `La pizza de
  mozzarella chica es sin aceitunas` → one `set_observacion_producto`, while
  `quiero una pizza de mozzarella chica sin aceitunas` remains add.
- [x] 6.3 Run the focused validation commands from `proposal.md`, including
  strict OpenSpec validation and `git diff --check`.
- [ ] 6.4 After approved deploy, verify unique declarative set and explicit
  clear on a known own line: no quantity change, no extra line, and cleared
  context/pending.

## 7. Regression amendment: bounded declarative line-identity recovery

- [x] 7.1 Extend only the existing observation recognizer: after its bounded
  order-line fuzzy path yields zero candidates, recover candidates from
  deterministic identity evidence in the complete raw message and the same
  active-draft line catalog. Do not parse grammar, enumerate verbs, consult an
  LLM/catalog, widen candidates, or alter the stored raw observation text.
- [x] 7.2 Add focused own-line tests for qualified Mozzarella Chica and a
  second product/condition, plus zero/multiple evidence safety and no
  transaction-control regressions.
- [x] 7.3 Run the focused pytest, Ruff, compileall, strict OpenSpec validation
  and `git diff --check`; report complete output and pre-existing failures.
- [ ] 7.4 After approved deploy, repeat the declarative set gate on a known
  own line; verify only its observation changes, no quantity/line change, and
  context/pending clear. Keep 6.4 pending until its explicit clear is also
  verified.

## 8. Superseding amendment: confirmation-time order observation

- [x] 8.1 Replace the product-line-observation specification/contract with a
  confirmation-time, Pedido-level free-text observation flow. Retire direct
  observation classification guidance and line observation presentation;
  preserve existing data without migration.
- [x] 8.2 Make a valid explicit `confirmar_pedido` request create the bounded
  observation context after existing closure preconditions pass. Implement
  exact `no` skip and opaque valid-text capture; final capture and confirmation
  must be atomically staged by the existing caller-owned transaction.
- [x] 8.3 Disable direct product/pedido observation intent execution and
  safely clear a stale product-line observation pending context without a line
  write. Remove modules and seams that have no remaining caller.
- [x] 8.4 Add focused coverage for no/text/empty/over-limit, precondition and
  ownership revalidation, no classifier/LLM/product access in the capture
  turn, response privacy, stale-pending safety, direct-intent rejection, panel
  projection and transaction ownership.
- [x] 8.5 Run the exact focused pytest, Ruff, compileall, strict OpenSpec
  validation and `git diff --check` commands in `proposal.md`; record complete
  local-terminal output and known pre-existing failures.
- [ ] 8.6 Post-deploy pilot gate: complete one order with `no` and one with a
  free-text note; verify each order is confirmed, the note is present only on
  the Pedido where supplied, no line observation changes, and pending/context
  are cleared. Do not include customer content or identifiers in the report.
- [ ] 8.7 Request explicit approval before archiving. Earlier line-observation
  tasks 1–7 are superseded and remain historical; they are not archive gates.

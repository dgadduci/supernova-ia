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

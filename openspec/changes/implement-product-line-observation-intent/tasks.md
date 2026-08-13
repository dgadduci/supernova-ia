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

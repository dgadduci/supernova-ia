# Tasks
## 1. Specification and approval

- [x] 1.1 Inspect archived provider-outbound/worker OpenSpecs, active
  capability, coordinator-to-callback path, settings and focused tests.
- [x] 1.2 Confirm existing per-module logs, durable failure fields and worker
  output; distinguish them from centralized observability.
- [x] 1.3 Define safe Twilio attempt evidence independently of one provider
  code, preserving current retry policy and transaction boundaries.
- [x] 1.4 Obtain user approval before implementation.

## 2. Implementation (after approval)

- [x] 2.1 Add one sanitized dispatcher-owned Twilio attempt event for typed and
  technical outcomes, using only the approved field allowlist.
- [x] 2.2 Surface safe per-attempt evidence in the outbound CLI and safe
  outcome/category aggregates in the worker cycle.
- [x] 2.3 Preserve retry classification, durable state transitions, leases,
  callback behavior and all inbound/order isolation.
- [x] 2.4 Add focused adapter/dispatcher, CLI, worker and regression tests.

## 2a. Post-review corrections (implementer, scope-locked)

- [x] 2a.1 Remove the duplicate `_default_outbound_runner` definition in
  `backend/cli/run_provider_processing_worker.py` so the active runner resets
  `_WORKER_OUTBOUND_CELL.aggregate` BEFORE invoking the CLI and feeds the
  aggregate through the `cycle_aggregate_writer` seam. The previous duplicate
  left the cell stale and bypassed the writer seam in production.
- [x] 2a.2 Invoke `cycle_aggregate_writer` (when provided) with a fresh
  `OutboundCycleAggregate(technical_failure=1)` on every CLI early-exit path
  before the dispatcher runs: settings loader error, settings validation
  error, and Twilio client construction error. The dispatch failure path
  already invoked the writer; the three new branches preserve the same safe
  contract (no stale counts, no sensitive payload, only the exception class
  via the existing `_build_cycle_aggregate` helper).
- [x] 2a.3 Add focused regression tests for the cell-reset invariant, the
  Twilio client construction safe aggregate, the settings loader safe
  aggregate, the settings validation safe aggregate, and the no-double-
  dispatch invariant.

## 3. Validation and review (after implementation)

- [ ] 3.1 Implementer runs every exact command in `proposal.md` locally and
  supplies complete output; no validation is assumed passed without it.
- [ ] 3.2 Codex reviews scope, safe logging, state transitions, transaction
  ownership and complete validation output.
- [ ] 3.3 Do not commit, sync, archive, alter Railway/Twilio settings or run a
  production replay without separate user authorization.

> **Note.** Items 3.1, 3.2, and 3.3 remain unchecked: they depend on the
> Codex review of the post-review corrections and on separate user
> authorization. Validation output is provided in the implementer's
> final report but is NOT marked here until Codex confirms the scope is
> closed.
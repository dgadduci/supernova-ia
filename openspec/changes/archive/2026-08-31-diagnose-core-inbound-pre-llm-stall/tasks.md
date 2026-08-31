# Tasks: diagnose the core inbound pre-LLM stall

## 1. Diagnostic contract

- [x] 1.1 Register the closed `provider_inbound_checkpoint` event and its
  validation rules, allowlists and safe correlation field.
- [x] 1.2 Add focused observability tests for valid, invalid, bounded and
  privacy-safe payloads.

## 2. Core checkpoints

- [x] 2.1 Emit the availability result after the existing evaluation returns,
  without changing the availability decision.
- [x] 2.2 Emit session-loaded, draft-stage and flush checkpoints around the
  existing session/order staging sequence, without adding transaction control.
- [x] 2.3 Emit the closed business-dispatch branch immediately before the
  existing dispatcher call, preserving initial and pending-context behavior.
- [x] 2.4 Preserve existing stage events, LLM timing/correlation, processing
  outcomes, leases, retries and outbox behavior unchanged.

## 3. Focused validation and report

- [x] 3.1 Add coordinator/integration tests for checkpoint order and partial
  traces, including an LLM timeout boundary.
- [x] 3.2 Run the focused pytest, Ruff, compileall, strict OpenSpec and diff
  checks from `proposal.md` and report complete output.
- [x] 3.3 Report exact files changed, privacy guarantees, unresolved limits
  and confirm that sync, archive, commit, push, PR, Railway and deploy were
  not executed.

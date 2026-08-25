# Tasks: diagnose provider-worker progress stalls

## 1. Closed observability contract

- [x] 1.1 Extend the existing worker-liveness phase allowlist with only
  `inbound_runner` and `cycle_summary`.
- [x] 1.2 Add focused production-observability tests for valid new phases and
  invalid/free-form/sensitive payload rejection.

## 2. Worker boundaries

- [x] 2.1 Emit nested inbound-runner evidence after existing SIGALRM arming
  and around exactly one existing inbound-runner invocation.
- [x] 2.2 Emit cycle-summary evidence around exactly one existing summary
  writer invocation, preserving event/call order and all existing re-raises.
- [x] 2.3 Preserve current timeout, signal restoration, transaction/lease,
  readiness, outbound, sleep and supervisor semantics.

## 3. Operator evidence and validation

- [x] 3.1 Add a read-only, privacy-safe Railway log query and trace
  interpretation to the existing development guide.
- [x] 3.2 Run the focused pytest, Ruff, compileall, strict OpenSpec and diff
  checks from `proposal.md`; report complete output.
- [x] 3.3 Report exact files changed, last-boundary diagnostic limits and
  confirm no commit, push, PR, sync, archive, Railway action or deploy.

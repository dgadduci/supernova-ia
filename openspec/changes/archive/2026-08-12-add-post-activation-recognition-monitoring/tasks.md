# Tasks

## 1. Proposal and approval

- [x] 1.1 Inspect the archived safe-observability and post-4.12B verification
  changes plus the existing query boundary.
- [x] 1.2 Define a documentation-only scope, explicit per-window authorization,
  closed aggregate contract, stop conditions and deferred limits.
- [x] 1.3 User approved the design before any implementation or production
  query.

## 2. Implementation

- [x] 2.1 Add only the approved operator runbook/specification artifacts; do
  not modify application code or Railway state.
- [x] 2.2 Define the exact safe aggregate record and human-decision handoff.

## 3. Validation and handoff

- [x] 3.1 User ran strict OpenSpec validation successfully and `git diff
  --check` without output.
- [x] 3.2 Review scope and approve the documentation artifacts.
- [x] 3.3 The user separately authorized sync/archive; the change was archived
  without a production query.

# Tasks: fix-provider-worker-stuck-turn-recovery

## Specification and implementation

- [x] 1.1 Add and validate the positive inbound-pass timeout setting with a
  safe default compatible with configured model timeouts.
- [x] 1.2 Enforce the timeout only around the existing automatic inbound pass;
  restore the timer/handler on every return path.
- [x] 1.3 Propagate timeout through the existing worker supervisor path without
  calling transaction or lease repair methods and without invoking outbound.
- [x] 1.4 Correct the exact no-outbox Emulator status mapping.
- [x] 1.5 Update browser behavior only if required by the corrected wire status;
  preserve neutral polling and existing conversation history.

## Tests and validation

- [x] 2.1 Add focused worker tests for normal completion, timeout propagation,
  outbound non-invocation, timer cleanup and safe configuration failure.
- [x] 2.2 Add focused status projection tests for pending, leased, retryable,
  terminal, processed-without-response and missing-receipt states.
- [x] 2.3 Add/update browser contract tests for pending polling and neutral
  exhaustion without an Emulator rejection.
- [x] 2.4 Run the focused pytest, Ruff, compileall, strict OpenSpec validation
  and git diff checks from the proposal.
- [x] 2.5 Report all pre-existing failures separately; do not fix unrelated
  debt.

## Operational handoff

- [x] 3.1 Do not run OpenSpec sync or archive as part of implementation.
- [x] 3.2 Do not commit, push, create a PR, change Railway variables or deploy
  without explicit authorization after review.

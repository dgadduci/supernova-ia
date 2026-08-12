# Tasks

## 1. Contract

- [x] 1.1 Add the closed `shadow_product_recognition` event/component and its
  field allowlists/validators to the shared observability schema.
- [x] 1.2 Preserve strict rejection of sensitive, unknown and incompatible
  event fields.

## 2. Integration

- [x] 2.1 Route `ShadowMetricsRecorder` through the shared event emitter once
  per existing observation, without changing recognition decisions or
  transaction ownership.
- [x] 2.2 Preserve safe emission-failure behavior and remove no fallback or
  business-outcome distinction.

## 3. Verification

- [x] 3.1 Add focused catalogue/privacy/round-trip tests.
- [x] 3.2 Add focused recorder tests for modes, technical fallback and
  no-side-effects.
- [x] 3.3 Extend the bounded query-CLI tests for the new event and raw-log
  rejection safety.
- [x] 3.4 Run the focused pytest, Ruff, compileall and strict OpenSpec
  validation commands from the proposal.

## 4. Operational follow-up

- [x] 4.1 After a separately authorized deploy, run one finite read-only
  production query; treat no events as inconclusive. Completed 2026-08-12:
  the bounded query returned zero events, an inconclusive result.

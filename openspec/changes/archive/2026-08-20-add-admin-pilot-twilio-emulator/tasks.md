# Tasks: add admin pilot Twilio emulator

## 1. OpenSpec and boundary

- [ ] 1.1 Confirm the existing local-only admin/pilot route remains unchanged.
- [ ] 1.2 Confirm the T-C webhook, NovaOrders ingress, coordinator, worker,
  outbox and dispatcher remain the only business pipeline.
- [ ] 1.3 Define the closed emulator configuration and generated credential
  contract, including fail-closed behavior.

## 2. Twilio emulator

- [ ] 2.1 Add the standalone `twilio_emulator/` package/service with health,
  authenticated control and bounded capture surfaces.
- [ ] 2.2 Implement generated Twilio-shaped account SID/auth token handling
  without exposing values in logs or responses.
- [ ] 2.3 Implement complete-form Twilio signature generation and the
  configured-T-C-only inbound forward.
- [ ] 2.4 Implement the Twilio-shaped outbound Messages API with HTTP Basic
  authentication, deterministic fake `SM...` identifiers and bounded capture.
- [ ] 2.5 Add tests proving no real Twilio host or SDK call is reached.

## 3. Provider transport modes

- [ ] 3.1 Add explicit `real`/`emulator` mode to the T-C provider client,
  preserving the existing real mode as default.
- [ ] 3.2 Add the equivalent opt-in emulator transport seam to the central
  Twilio outbound adapter.
- [ ] 3.3 Reject emulator mode when required test configuration is missing;
  never fall back to real Twilio.
- [ ] 3.4 Add focused tests for real-mode preservation, emulator-mode send,
  fake SID mapping and failure classification.

## 4. Admin/pilot integration

- [ ] 4.1 Add a separate authenticated emulator-test route and keep
  `local-test` local-only.
- [ ] 4.2 Validate exact Pedido/Session/Cliente/Comercio/channel identity,
  commerce availability, active installation and emulator enablement.
- [ ] 4.3 Add the detail-page action and bounded browser polling for the exact
  synthetic inbound identifier.
- [ ] 4.4 Project existing receipt/outbox state and simulated outbound text
  without adding a database table or synchronously invoking the worker.
- [ ] 4.5 Add admin-panel tests for happy path, disabled mode, unavailable
  commerce, cross-commerce mismatch, delayed worker status and local-route
  preservation.

## 5. Observability and validation

- [ ] 5.1 Add safe structured emulator/admin outcome events to the existing
  catalogue.
- [ ] 5.2 Add privacy tests for credentials, signatures, addresses, bodies,
  raw forms and exception text.
- [ ] 5.3 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check` using the exact commands in the proposal.
- [ ] 5.4 Report changed files, complete validation output and unresolved
  limitations.

## 6. Explicitly out of scope

- [ ] 6.1 Do not alter the existing local-only admin chat semantics.
- [ ] 6.2 Do not call or configure real Twilio from emulator mode.
- [ ] 6.3 Do not add migrations, a second worker, a second business pipeline,
  provider callbacks, production enablement or deployment actions.
- [ ] 6.4 Do not sync or archive until review and validation are complete.

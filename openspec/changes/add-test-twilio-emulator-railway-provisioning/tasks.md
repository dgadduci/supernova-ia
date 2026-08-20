# Tasks: provision the test Twilio Emulator on Railway

## 1. Boundary and reproducible service

- [x] 1.1 Confirm the archived admin/pilot emulator code and existing local
  route remain unchanged.
- [x] 1.2 Add only the minimal standalone service definition needed to start
  `twilio_emulator.app:create_app` on Railway's `$PORT` with `/health`.
- [x] 1.3 Confirm the service does not run migrations, a worker or NovaOrders
  database code.

## 2. Test-only Railway provisioning

- [ ] 2.1 Create/configure one `twilio-emulator` service in Railway `core/test`.
- [ ] 2.2 Configure its HTTPS T-C webhook URL, control token and pinned
  synthetic Twilio-shaped credentials without exposing values.
- [ ] 2.3 Verify build, startup, healthcheck and bounded non-secret health
  response.

## 3. Coordinated core and T-C configuration

- [ ] 3.1 Configure the required `supernova-ia` emulator mode, feature flag,
  emulator URL, synthetic credentials and control token in `test`.
- [ ] 3.2 Configure the required `tc-comercio-1` emulator mode, emulator URL
  and the exact same synthetic credential pair in `test`.
- [ ] 3.3 Verify production and `calibracion` variables are unchanged.
- [ ] 3.4 Verify core and T-C startup/configuration fail closed if the shared
  contract is incomplete or mismatched.

## 4. Focused verification

- [ ] 4.1 Run focused emulator, T-C startup and admin/pilot tests locally.
- [ ] 4.2 Run Ruff and compileall on any touched Python files.
- [ ] 4.3 Validate the change with `openspec validate add-test-twilio-emulator-railway-provisioning --strict`.
- [ ] 4.4 Verify the authenticated panel displays `Enviar por Twilio Emulator`
  only after activation.
- [ ] 4.5 Execute one active-order E2E message and observe accepted/pending/
  sent status plus synthetic SID through the existing worker/outbox path.

## 5. Rollback evidence

- [ ] 5.1 Record the prior real-mode configuration without exposing values.
- [ ] 5.2 Disable test emulator mode and verify the panel hides the emulator
  action while local behavior remains available.
- [ ] 5.3 Report service/deployment IDs, bounded health result, validation
  output and unresolved limitations.

## 6. Explicitly out of scope

- [ ] 6.1 Do not change production or `calibracion`.
- [ ] 6.2 Do not rotate real Twilio credentials or change real webhooks.
- [ ] 6.3 Do not add migrations, fixtures, a second worker or a second
  business-processing pipeline.
- [ ] 6.4 Do not sync or archive until implementation review and validation
  are complete.

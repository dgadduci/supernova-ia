# Proposal: provision the test Twilio Emulator on Railway

## Objective

Complete the operational part of the archived `add-admin-pilot-twilio-emulator`
change by running the existing `twilio_emulator` package as a dedicated Railway
service in `test`, and by enabling the admin/pilot action only after the core,
T-C and emulator share a coherent test-only configuration.

The result must make the `Enviar por Twilio Emulator` action visible in the
authenticated pilot panel and allow one bounded end-to-end test through the
existing T-C, NovaOrders ingress, provider worker, outbox and dispatcher path,
without contacting real Twilio or changing production.

## Current execution path

PR #111 is deployed successfully in `supernova-ia` and contains the new panel
template and route. The panel hides the emulator action unless all of the
following are true: `TWILIO_PROVIDER_MODE=emulator`,
`COMMERCE_ISOLATED_OUTBOUND_ENABLED=1`, and the complete core emulator
configuration is valid.

The Railway `test` environment currently has no `twilio-emulator` service, and
the core/T-C emulator variables are not configured. Consequently the existing
local-only panel remains visible while the new emulator action is correctly
hidden by its fail-closed gate.

## Scope

- Add a reproducible standalone service definition for the existing
  `twilio_emulator` application, including its start command, port and
  `/health` check.
- Provision that service only in Railway `core/test`.
- Configure the emulator's server-side test credentials, control token and
  T-C webhook target.
- Configure the corresponding core variables:
  `TWILIO_PROVIDER_MODE`, `COMMERCE_ISOLATED_OUTBOUND_ENABLED`,
  `TWILIO_EMULATOR_BASE_URL`, `TWILIO_EMULATOR_ACCOUNT_SID`,
  `TWILIO_EMULATOR_AUTH_TOKEN` and `TWILIO_EMULATOR_CONTROL_TOKEN`.
- Configure the corresponding T-C variables:
  `TC_TWILIO_PROVIDER_MODE`, `TC_TWILIO_EMULATOR_BASE_URL`,
  `TC_TWILIO_EMULATOR_ACCOUNT_SID` and `TC_TWILIO_EMULATOR_AUTH_TOKEN`.
- Verify that all three services use the same synthetic account SID/auth token,
  that the emulator points only to the dedicated T-C webhook, and that the
  panel action traverses the existing asynchronous pipeline.
- Document safe rollback by disabling emulator mode and removing only the
  test-only service/configuration.

## Non-goals

- No production or `calibracion` changes.
- No real Twilio credential rotation, webhook change or outbound send.
- No change to the local-only admin/pilot route.
- No new worker, queue, database table, migration or business-processing path.
- No generated credentials at process startup; credentials must be explicitly
  pinned and shared across the three test services.
- No exposure of secrets in repository files, logs, health responses or the
  browser.

## Shared boundary

The shared boundary remains the T-C provider transport. The emulator owns only
Twilio-shaped HTTP behavior and bounded in-memory captures. T-C remains the
only commerce-owned provider adapter, NovaOrders remains the owner of durable
receipt/outbox state, and the existing worker/dispatcher remain asynchronous
owners of outbound processing.

## Configuration and fallback behavior

The emulator service SHALL fail closed if any required `EMULATOR_*` value is
missing or malformed. The core and T-C SHALL remain in `real` mode unless the
operator explicitly enables emulator mode in `test`.

If the emulator, T-C webhook or outbound emulator API is unreachable, the
admin action reports its existing bounded rejection/technical failure and does
not fall back to real Twilio, the local processor or a second pipeline.

The emulator control token is server-to-server. The synthetic Twilio-shaped
account SID and auth token are shared only among emulator, T-C and core
transport configuration; they are never sent to real Twilio or returned to the
admin browser.

## Transaction ownership

This change owns no NovaOrders transaction. The emulator has no database. The
existing coordinator, provider worker, outbox dispatcher and T-C adapter keep
their current transaction and lease ownership.

## Observability

Verify only bounded health/deployment status and the existing safe emulator,
admin and provider outcome events. Do not log credentials, control tokens,
URLs, signatures, phone numbers, message bodies or raw exception text.

## Expected files and external targets

- A focused service/deployment definition under `twilio_emulator/` if needed
  for reproducible Railway startup.
- A short operator runbook describing the three-service variable contract and
  test-only rollback.
- No application business logic changes unless the existing service cannot be
  started reproducibly as a standalone process.
- Railway `core/test`: one new `twilio-emulator` service and configuration on
  `supernova-ia` and `tc-comercio-1`.

## Focused validation

- Strict OpenSpec validation.
- Focused emulator and T-C startup/configuration tests.
- Focused admin/pilot emulator tests.
- Ruff and compileall on any touched Python files.
- Railway emulator `/health` returns `200` without secret fields.
- Admin panel displays the emulator action only after the complete test
  configuration is present.
- One controlled end-to-end message reaches the existing worker/outbox path
  and returns a synthetic provider SID; real Twilio remains untouched.

## Rollback and reversibility

Disable `TWILIO_PROVIDER_MODE` and `TC_TWILIO_PROVIDER_MODE` in `test`, set
`COMMERCE_ISOLATED_OUTBOUND_ENABLED` back to its previous value if it was
introduced solely for this test, and remove the emulator-only variables or
service. The existing local panel and real provider configuration remain
available. No migration or data deletion is required.

## Deferred limitations

The emulator remains a bounded transport harness. It does not emulate carrier
delivery, WhatsApp behavior, real Twilio callbacks or production traffic.

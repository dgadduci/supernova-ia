# Proposal: use the emulator credential for T-C inbound signatures

## Objective

Correct T-C inbound signature validation when `TC_TWILIO_PROVIDER_MODE=emulator`.
The emulator signs inbound requests with `EMULATOR_TWILIO_AUTH_TOKEN`, whose T-C
counterpart is `TC_TWILIO_EMULATOR_AUTH_TOKEN`. Real mode must continue using
`TC_TWILIO_AUTH_TOKEN`.

## Current execution path

T-C configuration already loads both the real Twilio credential and the emulator
credential. The outbound path already selects the mode-appropriate credential.
The inbound webhook currently always validates with `config.twilio_auth_token`.
Consequently, a synthetic inbound request is rejected with HTTP 403 unless the
real Twilio credential is reused, which breaks test credential isolation.

## Scope

- Select the inbound validation credential from the explicit provider mode.
- Preserve the existing HTTP status, TwiML, routing, forwarding, coordinator,
  transaction, and observability behavior.
- Add focused tests for valid and invalid credentials in both modes.
- Keep real mode behavior unchanged.

## Non-goals

- No new environment variable or configuration parser.
- No outbound path change.
- No changes to the emulator service, Admin/Pilot, worker, outbox, or NovaOrders.
- No database migration, credential rotation, Railway configuration, or deploy.
- No fallback to the other credential and no retry with another mode.

## Shared boundary

The shared boundary is the T-C inbound webhook signature validator. The explicit
`CommerceAdapterConfig.provider_mode` selects the credential used by that
validator.

## Authoritative outcomes and failure behavior

- In `real` mode, validate only with `twilio_auth_token`.
- In `emulator` mode, validate only with `twilio_emulator_auth_token`.
- Existing fail-closed configuration validation remains authoritative when the
  emulator credential is missing or invalid.
- A credential mismatch keeps the existing HTTP 403 behavior and must not invoke
  routing, forwarding, or the coordinator.
- Validation must not retry with or fall back to the other credential.

## Transaction ownership

Unchanged. Signature validation remains before downstream processing and does not
take ownership of caller-managed transactions.

## Observability

Reuse the existing bounded signature-rejection event. Do not log or expose
tokens, signatures, request bodies, phone numbers, raw exception details, or
other PII/secrets.

## Expected files

- `commerce_adapter/app/routes/webhook.py` (or a directly related existing
  helper, if needed).
- `commerce_adapter/tests/test_webhook_route.py`.
- This OpenSpec change and its focused task/spec artifacts.

## Focused tests and validation

The implementer must run and report the complete output of:

```text
PYTHONPATH=. venv/bin/python -m pytest commerce_adapter/tests/test_webhook_route.py commerce_adapter/tests/test_startup_fail_closed.py -q
PYTHONPATH=. venv/bin/ruff check commerce_adapter/app/routes/webhook.py commerce_adapter/app/config.py commerce_adapter/tests/test_webhook_route.py
PYTHONPATH=. venv/bin/python -m compileall -q commerce_adapter/app/routes/webhook.py commerce_adapter/app/config.py
openspec validate fix-tc-emulator-inbound-signature-auth --strict
git diff --check
```

Tests must demonstrate that emulator mode accepts only the synthetic credential,
real mode accepts only the real credential, and neither path calls a real Twilio
endpoint or SDK.

## Rollback and reversibility

Rollback is a code revert of the mode-aware token selection. No database or
Railway rollback is part of this change. Emulator mode remains disabled until
the corrected code is merged, deployed, configured, and verified separately.

## Deferred limitations

Railway variable configuration and end-to-end testing through the deployed
emulator are deferred until this correction is merged and deployed under a
separate operational authorization.

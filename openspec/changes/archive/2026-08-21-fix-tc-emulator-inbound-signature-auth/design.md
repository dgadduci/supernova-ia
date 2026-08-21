# Design: mode-aware T-C inbound signature authentication

## Decision

Use the provider mode already resolved by `CommerceAdapterConfig` to choose the
single credential passed to the existing inbound Twilio signature validator:

```text
provider_mode == real     -> twilio_auth_token
provider_mode == emulator -> twilio_emulator_auth_token
```

Do not add a setting, alter environment parsing, or introduce a second
validation pipeline.

## Execution sequence

1. The T-C configuration resolves the explicit provider mode and both credential
   fields using the existing configuration contract.
2. The inbound webhook selects exactly one credential from that mode.
3. The existing validator checks the complete Twilio form and signature.
4. On success, the existing canonicalization, routing, and NovaOrders path runs.
5. On failure, the existing 403 response and bounded rejection event remain in
   force, with no downstream side effects.

For emulator mode, the emulator signs with `EMULATOR_TWILIO_AUTH_TOKEN`, the
T-C receives the corresponding `TC_TWILIO_EMULATOR_AUTH_TOKEN`, and the existing
inbound path continues after validation.

## Failure matrix

| T-C mode | Signing credential | Expected result |
|---|---|---|
| `real` | real token | Existing inbound path accepted |
| `real` | emulator token | HTTP 403, no downstream processing |
| `emulator` | emulator token | Existing inbound path accepted |
| `emulator` | real token | HTTP 403, no downstream processing |
| `emulator` | missing/invalid emulator token configuration | Existing fail-closed configuration behavior |

## Security and data boundaries

The selected credential is used only inside the existing signature validator. It
must not appear in logs, HTTP responses, TwiML, observability payloads, or error
messages. Signature validation remains before database access and downstream
side effects.

## Test design

Extend the existing webhook route coverage with distinct real and synthetic
tokens. Cover valid emulator-mode validation, rejection of a real-token
signature in emulator mode, valid real-mode validation, and rejection of a
synthetic-token signature in real mode. Keep outbound tests unchanged because
the outbound mode-aware credential selection is already correct.

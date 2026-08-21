# Design: dedicated browser contract for the emulator action

## Decision

Keep the existing FastAPI request models and add a dedicated browser-side
handler for `[data-debug-emulator-form]`. The handler must use the same JSON
and same-origin pattern already used by the local-test form, while keeping its
own selectors, status area and origin header.

The detail template will expose the already generated `emulator_status_url`
as a data attribute on the emulator form. No URL or credential will be
constructed from operator input.

## Request sequence

```text
operator enters message
  -> emulator form handler prevents native form navigation
  -> POST JSON {"message": "..."} + X-Emulator-Test-Origin: same-origin
  -> existing Admin/Pilot emulator route
  -> bounded synthetic_inbound_id response
  -> POST status JSON {"synthetic_inbound_id": "..."}
  -> existing receipt/outbox projection
  -> bounded status and optional outbound text/SID rendered in the page
```

The control token remains entirely server-side. The browser only receives the
synthetic identifier and the already bounded status projection.

## Polling behavior

The handler starts polling only after a successful submit response with a
non-empty `synthetic_inbound_id`. It accepts only the six statuses defined by
`EmulatorStatusResponse`. `sent`, `retryable` and `terminal` finish the flow;
`accepted`, `processed` and `pending` remain transitional. Polling must have a
bounded interval/count or deadline so a failed worker cannot create an
unbounded browser loop.

The handler must render the bounded `outbound_body` and
`provider_message_sid` only when present. It must not render raw response
objects, validation details or exception text.

## Error behavior

For a rejected submit, malformed response, failed status request or exhausted
polling bound, the page shows a generic emulator failure/status message and
re-enables the form. It does not submit again automatically and never invokes
the local form or a real provider as fallback.

## Local channel isolation

The existing `[data-debug-form]` handler remains unchanged. The emulator
handler must query only `[data-debug-emulator-form]` and emulator-specific
selectors so a submit cannot append to or mutate the local transcript.

## Test design

Use the existing Admin/Pilot template tests to assert the emulator form and
status URL data attribute are present when enabled and absent when disabled.
Assert the rendered script contains the emulator JSON content type, the
`X-Emulator-Test-Origin` header, the emulator selectors and the status request
shape. Keep the existing route tests with `json={"message": "hola"}` as the
authoritative server contract and add no form-urlencoded route acceptance.

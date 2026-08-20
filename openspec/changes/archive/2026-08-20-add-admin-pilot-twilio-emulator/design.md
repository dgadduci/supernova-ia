# Design: admin/pilot through a Twilio emulator

## Decision

Add a small standalone `twilio_emulator` transport service and make the
admin/pilot test action an explicit provider-shaped driver. The emulator owns
only provider-shaped HTTP behavior and bounded test capture. It does not
duplicate NovaOrders business processing.

## Components

### Twilio emulator

The emulator has two distinct surfaces:

1. **Inbound control surface**

   An authenticated test-only command receives the already validated test
   source/destination/body from the admin server. The emulator generates a
   unique synthetic `MessageSid`, builds the complete Twilio form, computes
   the standard Twilio signature with its generated test auth token and POSTs
   the form to the single configured T-C webhook URL. The emulator never
   accepts a target URL from the browser or request body.

2. **Outbound Messages API**

   The emulator exposes the narrow Twilio `Messages.create` HTTP contract
   needed by the T-C and central transport seams. It validates the generated
   account SID/auth token with HTTP Basic authentication, accepts one message
   request, stores a bounded capture and returns a synthetic `SM...` SID and
   accepted status. It does not call the Twilio SDK or any external provider.

The control token and generated provider credentials are loaded from
environment variables. The service refuses to start unless the explicit
emulator mode and test-only configuration are present. It has bounded
retention and no durable NovaOrders state.

### T-C adapter

The adapter configuration gains an explicit provider mode. In `real` mode it
keeps the existing Twilio SDK path. In `emulator` mode it constructs an
HTTP client for the emulator Messages API using the generated test
credentials. The outbound route, canonical command, installation HMAC and
idempotency behavior remain unchanged.

The T-C webhook remains the inbound target. The emulator's signing behavior
therefore exercises the existing signature validation, canonicalization and
NovaOrders forwarding code instead of introducing a bypass route.

### Central Twilio adapter

The existing central outbound adapter gets the same explicit opt-in
transport selection for controlled tests. Its real mode remains the default.
The emulator mode uses the same typed send result and retry/terminal mapping
without making the central dispatcher aware of emulator implementation
details.

### Admin/pilot action

The current `local-test` action remains unchanged and continues to be labelled
local-only. The detail page gains a separate form/action labelled
`Enviar por Twilio Emulator`.

The new route:

1. authenticates the operator and same-origin request;
2. loads the exact selected Pedido and active Session;
3. validates client, commerce, dedicated channel, commerce availability,
   active T-C installation and emulator-enabled test configuration;
4. calls the emulator inbound control surface from the server side;
5. returns the synthetic inbound identifier and a bounded polling token;
6. never calls the coordinator, worker, dispatcher or T-C directly.

The browser polls a read-only status route scoped to the exact selected
Pedido/Session and synthetic inbound identifier. The route reads the existing
provider receipt and outbox rows, and returns a closed status such as
`accepted`, `processed`, `pending`, `sent`, `retryable` or `terminal` plus
the bounded outbound text for the authenticated test console. It does not
create state or poll the emulator as a second source of truth.

## Request sequence

```text
Admin browser
  -> NovaOrders admin emulator action
  -> twilio_emulator control/inbound
  -> T-C /webhooks/twilio/whatsapp/inbound
  -> NovaOrders internal accept-event
  -> existing coordinator commit
  -> existing provider worker
  -> existing outbox dispatcher
  -> T-C /internal/commands/send-message
  -> twilio_emulator Messages API
  -> fake MessageSid
  -> existing outbox finalization
  -> admin status polling
```

No step invokes the real Twilio network when emulator mode is active.

## Security boundaries

- The emulator control token is server-to-server and never reaches the
  browser.
- The generated Twilio-shaped auth token is held by the emulator and T-C
  configuration only; NovaOrders does not receive it.
- The admin route signs no Twilio webhook and cannot select an arbitrary
  destination. The emulator signs the form with its own generated token.
- The emulator outbound API accepts only its generated account SID/token and
  never accepts an arbitrary callback or target URL.
- Emulator mode is explicit, test-only and fail-closed. A missing mode,
  target, control token or credential is a startup/configuration error.
- Operational logs contain only bounded event metadata. Test message text is
  returned only by the authenticated status projection.

## Failure and rollback

If the emulator is disabled, unavailable or misconfigured, the admin action
returns a bounded error and does no business work. It never falls through to
the local processor, real T-C or central Twilio.

Disabling emulator mode restores the real T-C/central transport defaults. The
existing local-only panel action remains independently available throughout
rollback.

## Why no migration is needed

The synthetic inbound identifier is stored in the existing provider receipt
identity. The resulting response is stored in the existing outbound row.
The emulator's transport capture is bounded and ephemeral; durable status is
read from NovaOrders' existing receipt/outbox state.

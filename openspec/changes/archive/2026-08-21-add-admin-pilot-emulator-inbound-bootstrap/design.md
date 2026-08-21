# Design: Admin/Pilot bootstrap for a clean emulator inbound

## Decision

Extend the existing authenticated Admin/Pilot order operations surface with a
small bootstrap form. The form is a driver for the existing emulator inbound
control contract, not a second order-creation pipeline.

The operator supplies:

- `cliente_id` — positive integer;
- `comercio_id` — positive integer;
- `message` — bounded nonblank plain text, up to the same limit as the current
  emulator test action.

The UI may use two numeric text inputs for the IDs and one message textarea.
The message control is required because a Twilio inbound command must contain
the customer message that the normal processor will interpret.

## Current-path integration

The route reuses the existing seams:

1. Authenticate with the existing Admin/Pilot HTTP Basic dependency and require
   the same-origin bootstrap header.
2. Parse and bound the three form values with the existing Pydantic/route
   conventions.
3. Resolve the exact active `Cliente` by ID and its canonical WhatsApp E.164.
4. Resolve the active dedicated Twilio channel for `comercio_id` and use its
   canonical destination E.164. The browser cannot submit an arbitrary number.
5. Reuse the commerce availability policy, active T-C installation guard and
   explicit emulator configuration validation.
6. Query the existing active-session identity for the exact client/commerce
   pair. If one exists, reject without closing or changing it; this prevents
   the bootstrap action from creating ambiguous concurrent order contexts.
7. Call `build_emulator_control_client(...).submit_inbound(...)` with the
   server-resolved source, destination and operator body.
8. Return only the synthetic inbound identifier and a closed result state.
   The worker later creates the active Session and draft Pedido through the
   normal provider processing path.

## Sequence

```text
Operator browser
  -> POST /admin/pilot/orders/emulator-bootstrap
     (client id, commerce id, body)
  -> NovaOrders validates identity and configuration
  -> emulator /internal/emulator/inbound
  -> signed T-C webhook form
  -> T-C -> NovaOrders acceptance
  -> existing worker
  -> stage active Session + draft Pedido + outbound outbox
  -> existing outbound T-C/emulator path
```

The route does not call the T-C webhook, provider coordinator, worker or
dispatcher directly. The emulator remains the only entry point for the
synthetic provider inbound.

## UI behavior

Place the form on the Admin/Pilot orders list because no existing Pedido is
needed. Label it explicitly, for example `Iniciar inbound de cliente por
Twilio Emulator`. Show a bounded accepted/unavailable result and the synthetic
inbound identifier only. On accepted submission, refresh the order listing
after a short bounded delay or provide a `Actualizar pedidos` action; do not
pretend that the HTTP acceptance means the worker has already created the
Pedido.

The existing detail-page action remains unchanged and continues to require a
non-draft Pedido. The existing local-test channel remains local-only.

## Failure behavior

Every validation failure, active-context conflict, emulator rejection or
transport failure returns one generic browser-safe rejection. The route emits
the closed reason category for operations but never exposes which identifier,
address, credential or downstream detail caused it. No fallback to the local
processor or real Twilio is permitted.

## Security and privacy

- The control token and synthetic Twilio credentials never reach the browser.
- The browser supplies IDs, not E.164 addresses or target URLs.
- The message body is bounded and is returned nowhere in the response or logs.
- Client/commerce identifiers are not included in the bounded event payload.
- Same-origin protection prevents cross-site form submission in addition to
  the existing Admin/Pilot authentication.

## Transaction and persistence

The request-level SQLAlchemy session remains the dependency owner. The route
performs read-only validation and an outbound HTTP call only. It must not
commit, rollback, flush, refresh, begin or close. No schema or migration is
needed: the existing provider receipt, processing row, session, pedido and
outbox are the durable records created by the existing pipeline.

## Testing strategy

Use route tests with injected/fake emulator client seams and service tests for
identity and active-context decisions. Assert exact downstream call counts,
server-side address resolution, rejection before transport, response shaping,
transaction ownership and absence of secrets/raw input. Do not require
Railway, T-C, the worker, Twilio or a live database external to the existing
test fixtures.

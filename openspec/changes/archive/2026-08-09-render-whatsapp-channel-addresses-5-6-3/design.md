## Decision

The application keeps `TWILIO_OUTBOUND_SENDER_E164` and
`MensajeProveedorSaliente.destinatario_e164` in canonical bare E.164. Add an
adapter-local pure function that accepts that canonical representation and
returns `"whatsapp:" + value`. `send()` applies it immediately at the Twilio
SDK boundary:

```python
client.create(
    to=_as_whatsapp_address(request.destinatario_e164),
    from_=_as_whatsapp_address(request.sender_e164),
    body=request.cuerpo,
    status_callback=request.status_callback_url,
)
```

The function must not accept or normalize already-prefixed strings. That would
mix provider transport representation into an internal canonical contract and
would hide a caller/configuration defect. Existing validation remains the
authority for canonical shape.

## Rationale

Twilio documents WhatsApp `from` and `to` as channel addresses such as
`whatsapp:+14155238886`. The application intentionally strips that transport
prefix at inbound/routing/storage boundaries for provider-neutral commerce
resolution. Rendering the prefix at the sole outbound provider edge restores
the required wire representation without duplicating routing state or changing
environment-variable semantics.

## Invariants

- Stored destination, routing destination and sender setting remain bare,
  canonical E.164.
- Exactly one `whatsapp:` prefix is rendered for each SDK `to` and `from_`.
- `body` and `status_callback` are unchanged; no unsupported SDK argument is
  reintroduced.
- The adapter keeps real `TwilioRestException` classification by HTTP status.
- No transaction/control-flow/callback/retry behavior changes.
- No raw address is added to output or logs.

## Focused test design

Reuse the existing strict Messages-create seam and adapt its successful-send
assertions to expect `whatsapp:+` channel addresses for both sender and
recipient. The strict seam must retain exactly the supported four keyword
arguments. Add a small pure-function or direct adapter test that rejects an
already-prefixed/noncanonical input only if such validation is introduced by
the minimal implementation; do not duplicate a broad validation suite.

The current real-REST classification tests must continue to pass unchanged,
proving provider error behavior is not coupled to address rendering.

## Operational follow-up

After approved implementation, reviewed validation and deployment, send one
new controlled WhatsApp inbound message. Do not retry `mensaje_id=1`. Run one
manual pass bounded to one attempt and capture only the safe CLI summary.

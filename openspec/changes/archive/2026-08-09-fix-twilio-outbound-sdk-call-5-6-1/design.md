## Decision

Keep the existing `OutboundDispatchPayload.idempotency_key` and
`TwilioSendRequest.idempotency_key` as internal deterministic metadata for
the current dispatcher boundary. `send()` MUST NOT serialize or pass it to
`TwilioMessagesClient.create`. For the pinned Twilio `9.10.9` Message-create
seam, the adapter passes exactly:

```python
create(
    to=request.destinatario_e164,
    from_=request.sender_e164,
    body=request.cuerpo,
    status_callback=request.status_callback_url,
)
```

The internal key is intentionally not removed from the dispatch payload in
this corrective change: removing it would widen the public/internal typed
contract without repairing the production defect. It may be reconsidered only
in a separately approved cleanup after the pilot.

## Rationale

The Twilio Messages resource documents recipient, sender, content and status
callback fields for this send shape. It does not document an
`idempotency_key` create parameter. The real SDK rejects unknown keyword
arguments, whereas the existing `MagicMock` accepts them. The durable lease,
fresh lease token and conditional finalization already prevent concurrent
local finalizers and remain the sole local retry/idempotency mechanism.

## Runtime behavior

```mermaid
sequenceDiagram
    participant D as Dispatcher
    participant R as Outbox repository
    participant A as Twilio adapter
    participant T as Twilio SDK

    D->>R: claim one due row; commit lease
    D->>A: send(internal payload)
    A->>T: create(to, from_, body, status_callback)
    T-->>A: SID or typed provider/transport failure
    A-->>D: typed send result
    D->>R: conditional finalization with lease token
```

No step in this correction creates a transaction around the SDK call. A
`TypeError` caused by an unsupported keyword is prevented by construction and
by the strict test seam; it is not reclassified as a provider failure.

## Invariants

- The SDK call includes `to`, `from_`, `body` and `status_callback`, with
  their existing configured values.
- The SDK call includes no `idempotency_key` or other undocumented parameter.
- The row is claimed and the lease committed before the network call; the
  network call remains outside an open SQLAlchemy session.
- A returned SID still takes the existing conditional `accepted`
  finalization path; no callback behavior changes.
- Existing retryable/terminal classification remains unchanged.
- No body, address, signed URL or credential is added to logs, results,
  exceptions or test output.

## Focused test design

In `test_twilio_outbound_dispatcher.py`, replace the arbitrary-kwargs success
double for the accepted-send case with a small strict stand-in whose
`create()` signature has only `to`, `from_`, `body` and `status_callback`.
It returns an object containing a safe synthetic SID and records its received
fields for assertions. The test proves:

1. the accepted outcome and conditional finalization are preserved;
2. all four supported values are forwarded unchanged;
3. no `idempotency_key` reaches the SDK seam.

Do not use a `**kwargs` signature in that proof. Existing retry/terminal
tests may retain their suitable injected doubles if their purpose is failure
classification rather than production call-signature compatibility.

## Validation and operational boundary

Use the exact commands in `proposal.md` in the user's local terminal. The
implementer reports complete output, including strict OpenSpec validation.
After approval and reviewed validation only, the operator may wait for any
existing lease to expire and run one manually bounded dispatcher pass. That
production operation is not an implementation test and is not authorized by
this change.

## Why

The explicit production dispatcher pass reaches the outbound Twilio adapter
but fails with `TypeError` before sending. The adapter passes
`idempotency_key` to `twilio.rest.Client.messages.create`, although the
pinned Twilio Python SDK (`9.10.9`) does not accept that argument for Message
creation. Existing doubles accept arbitrary keyword arguments, so focused
tests did not represent the production call signature.

## Objective

Restore explicit outbound Twilio dispatch by sending only the documented and
SDK-supported Message-create arguments, while preserving the existing durable
outbox lease and conditional finalization as the idempotency/concurrency
boundary.

## Current execution path

`POST /webhooks/twilio/whatsapp/inbound` reaches
`ProviderInboundMessageCoordinator`, which stages durable outbound work in
the existing inbound transaction. An operator then invokes
`backend.cli.run_outbound_dispatch`; `OutboundMessageDispatcher` commits a
lease, calls `twilio_outbound_adapter.send` outside a database session, then
conditionally finalizes the row. The adapter currently calls
`messages.create(to=..., from_=..., body=..., status_callback=...,
idempotency_key=...)`, producing the technical failure after the lease has
been committed.

## Scope

- Remove the unsupported `idempotency_key` argument from the Twilio SDK call.
- Keep the internal deterministic outbox identifier only where it is already
  used inside the process; it must not be sent as a Twilio API parameter.
- Replace/update the focused adapter/dispatcher assertion with a strict
  Message-create stand-in compatible with Twilio `9.10.9`, proving the real
  payload shape and rejecting unsupported keyword arguments.
- Preserve existing accepted-send finalization, retry classification, lease
  recovery and the bounded manual CLI entry point.

## Non-goals

- No provider API idempotency scheme, custom HTTP client, SDK upgrade,
  retry-policy change, state-machine change, data migration or model change.
- No worker, scheduler, `docker-entrypoint`, `railway.toml`, inbound webhook,
  callback, routing, seeder or pilot-provisioning change.
- No direct production dispatch pass or mutation as part of implementation.

## Shared boundary, outcomes and fallback

| Condition | Authoritative outcome | Fallback |
| --- | --- | --- |
| Twilio accepts the supported create call and returns a SID | Existing row conditionally becomes `accepted` | none |
| Transport, 429 or 5xx failure | Existing bounded retryable path | later explicit bounded pass |
| Definitive provider failure | Existing terminal path | no resend |
| Unsupported SDK keyword detected by the focused seam | Test fails before release | remove the unsupported argument; do not invent a provider parameter |
| A lease from the pre-fix failure remains active | Existing expired-lease recovery makes it eligible only after expiry | do not run repeated passes before the approved fix |

The internal outbox lease plus lease-token conditional finalization remain the
idempotency/concurrency control. This change must not claim remote exactly-once
delivery, and it must not trigger fallback to TwiML, another channel, an
inbound replay or a rebuilt response.

## Transaction ownership and observability

The dispatcher continues to own its existing narrow claim and finalization
transactions; the Twilio adapter owns none. The network call remains outside
any SQLAlchemy session. Existing sanitized observability remains unchanged:
never log or print body text, E.164 values, URLs, credentials, Account SID,
Auth Token or raw provider payloads.

## Expected files

- `backend/services/twilio_outbound_adapter.py`
- `backend/tests/test_twilio_outbound_dispatcher.py`
- This OpenSpec change: proposal, design, capability delta and tasks

The implementer must inspect before adding any file. `backend/cli/` and the
PostgreSQL callback integration test are validation context, not expected edit
targets unless a failing focused test demonstrates a direct need.

## Focused tests and validation

The implementer shall run locally and provide complete output for:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_twilio_outbound_dispatcher.py backend/tests/test_run_outbound_dispatch_cli.py backend/tests/test_outbound_dispatcher_callback_integration.py
PYTHONPATH=. venv/bin/python -m ruff check backend/services/twilio_outbound_adapter.py backend/tests/test_twilio_outbound_dispatcher.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/twilio_outbound_adapter.py backend/tests/test_twilio_outbound_dispatcher.py
openspec validate fix-twilio-outbound-sdk-call-5-6-1 --strict
git diff --check
```

No validation is passed until the user supplies its complete output for review.

## Rollback and deferred limitations

Rollback is a source revert of this isolated adapter/test change; no database
rollback is involved. Remote delivery remains at-least-once under ambiguous
network outcomes, and an automated dispatcher remains explicitly deferred.

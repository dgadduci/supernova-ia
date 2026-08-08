## Why

The deployed dispatcher now safely records real Twilio REST failures. A bounded
pass returned terminal Twilio code `21660` after account credentials and sender
ownership were confirmed. The adapter currently passes canonical bare E.164
values directly as `from_` and `to`, but Twilio's WhatsApp Message API requires
channel addresses in the form `whatsapp:+E.164` for both fields.

## Objective

Render canonical stored/configured E.164 sender and recipient values as
WhatsApp channel addresses only at the Twilio outbound adapter boundary, so
Twilio receives `from_="whatsapp:+…"` and `to="whatsapp:+…"` while the
application's routing, configuration and durable outbox remain canonical bare
E.164.

## Current execution path

Inbound Twilio values are normalized by the existing provider/routing boundary
to bare canonical E.164. The outbox stores the recipient in that canonical
form, and `TWILIO_OUTBOUND_SENDER_E164` intentionally validates the same form.
`OutboundMessageDispatcher` passes both values into `build_send_request`, then
`twilio_outbound_adapter.send` currently forwards them unchanged to
`messages.create`. This loses the WhatsApp channel discriminator required by
the provider REST API.

## Scope

- Add one adapter-local pure rendering helper or equivalent local logic that
  turns canonical `+E.164` into `whatsapp:+E.164`.
- Apply it to both `from_` and `to` in the Twilio SDK call only.
- Update the strict SDK-compatible seam test to assert exact channel addresses
  and prove each source canonical value is rendered once.
- Preserve the existing SDK-supported argument set, real REST exception
  classification, lease/finalization behavior and safe observability.

## Non-goals

- No Railway variable change: `TWILIO_OUTBOUND_SENDER_E164` remains bare
  canonical E.164.
- No change to inbound normalization, `CanalWhatsapp`, routing, models,
  migrations, outbox data, dispatcher, CLI, callbacks, retries or Twilio
  account credentials.
- No support for multiple provider channels, arbitrary prefixes, Messaging
  Services, templates or outbound media.

## Shared boundary, outcomes and fallback

| Condition | Authoritative outcome | Fallback |
| --- | --- | --- |
| Canonical sender and recipient reach adapter | SDK receives `whatsapp:+E.164` for both | none |
| Twilio accepts the channel-address request | Existing conditional `accepted` finalization | none |
| Twilio returns retryable/terminal REST result | Existing typed classification/finalization | existing bounded policy |
| Invalid/noncanonical value reaches the adapter | Existing configuration/data validation failure remains visible | no string repair or cross-channel fallback |

No outcome may alter stored E.164 values, replay inbound processing, rebuild a
response, send SMS, use another channel or retry the terminal message already
recorded as id `1`.

## Transaction ownership and observability

The adapter stays database-free; the dispatcher retains the existing committed
lease, network call without a session and conditional finalization. Channel
address rendering is in-memory only. Do not log or print rendered addresses,
message bodies, provider exception text, account IDs, credentials or tokens.

## Expected files

- `backend/services/twilio_outbound_adapter.py`
- `backend/tests/test_twilio_outbound_dispatcher.py`
- This OpenSpec change: proposal, design, capability delta and tasks

Inspect before adding files. Any proposed change outside those boundaries
requires separate approval.

## Focused tests and validation

The implementer must run locally and report complete output:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_twilio_outbound_dispatcher.py backend/tests/test_run_outbound_dispatch_cli.py backend/tests/test_outbound_dispatcher_callback_integration.py
PYTHONPATH=. venv/bin/python -m ruff check backend/services/twilio_outbound_adapter.py backend/tests/test_twilio_outbound_dispatcher.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/twilio_outbound_adapter.py backend/tests/test_twilio_outbound_dispatcher.py
openspec validate render-whatsapp-channel-addresses-5-6-3 --strict
git diff --check
```

Known pre-existing integration-fixture failures require their exact unchanged
evidence and are not passing results. No production pass occurs until review of
the complete validation report and deployment.

## Rollback and deferred limitations

Rollback is a source revert only; no database state changes. The terminal
message id `1` remains terminal. Multi-channel rendering and a generic provider
address abstraction remain deferred.

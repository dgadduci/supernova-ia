## Why

Phase 5.4 can process exactly one already-authoritative inbound message, but
has no HTTP/provider boundary. Twilio must be authenticated before its form
payload is trusted, and its `From`, `To`, `MessageSid`, and `Body` must be
translated into the existing client/channel/core contracts without creating a
second processing transaction.

## Objective

Add one synchronous Twilio WhatsApp inbound webhook. It validates the Twilio
signature over the externally configured public URL and submitted form values,
resolves only an existing active client and the active destination channel,
then delegates a dedicated-channel message to the Phase-5.4 coordinator. It
returns well-formed TwiML acknowledgements/control replies and never owns
receipt idempotency or transaction completion.

## Current execution path

Twilio is not yet an HTTP dependency or router. `Cliente.whatsapp` is a unique
canonical number and `ClienteService`/`ClienteRepository` can resolve it.
`CommerceChannelResolver` resolves a provider-scoped destination only for an
active dedicated channel; it returns `requires_shared_routing` without
selecting a commerce. `ProviderInboundMessageCoordinator` accepts the final
`provider`, receipt id, channel id, client id, commerce id and raw message,
then owns the sole receipt/session/pipeline transaction. It deliberately does
not parse provider data, validate signatures or build TwiML.

## Scope

- Add the Twilio Python SDK dependency and a small provider-edge adapter that
  validates `X-Twilio-Signature` using `RequestValidator` and a configured
  public webhook base URL.
- Add a `POST` form webhook router for WhatsApp inbound messages. It accepts
  only the fields needed in this phase: `MessageSid`, `From`, `To`, and `Body`.
- Normalize provider phone envelopes through the existing canonical WhatsApp
  normalization, resolve an existing active client from `From`, resolve the
  destination through the existing dedicated-channel resolver, and create the
  exact Phase-5.4 command for the `twilio` provider.
- Return TwiML for accepted, duplicate and safe business-routing outcomes;
  invalid signatures must return `403` with no TwiML and no database/pipeline
  call. Technical failures propagate as HTTP failures so Twilio may retry.
- Add focused router/adapter tests, settings tests, a permanent OpenSpec
  capability and update application router registration.

## Non-goals

- No automatic customer creation, customer enrichment, phone reassignment,
  routing-code parsing, manual selection/switch HTTP UI, or processing of a
  shared channel. Those pre-commerce states remain safe TwiML control replies
  until a separately approved shared-channel conversation phase.
- No new receipt table, migration, transaction boundary, pipeline, recognizer,
  classifier, catalog, order or pending-context redesign. The 5.4 coordinator
  remains the only provider-processing transaction owner.
- No outbound delivery persistence, callback-state tracking, retries, status
  callback endpoint, response replay, or reconstruction of business responses
  from duplicate receipts. Those are Phase 5.6.
- No credentials in source, logging of auth tokens/signatures/raw body, or
  changes to the existing local incoming-message endpoint.

## Shared boundary, outcomes and fallback

The HTTP router owns only HTTP/form/TwiML translation. A Twilio adapter owns
only signature validation and canonical extraction. Existing services own
client lookup, destination resolution and core processing.

| Condition | HTTP/TwiML outcome | Processing behavior |
| --- | --- | --- |
| Missing/invalid signature or unavailable signature configuration | `403`, empty body | no database/core call |
| Valid request, active existing client, resolved dedicated destination, first receipt | `200` acknowledgement TwiML | invoke 5.4 once |
| Valid request, committed duplicate receipt | `200` empty TwiML | no pipeline/session mutation |
| Valid request but unknown/inactive client, invalid/unknown/inactive destination, unavailable dedicated commerce, or shared destination | `200` safe control TwiML | no 5.4 call |
| 5.4 `invalid_context` | `200` safe control TwiML | no fallback to another commerce/session |
| Adapter/coordinator/database/pipeline technical failure | propagate `5xx` | core rolls back when entered |

There is no fallback from a shared channel to a dedicated commerce, from a
missing customer to creation, from a bad signature to unsigned processing, or
from a duplicate to response replay. The TwiML acknowledgement after a first
commit is deliberately not a durable outbound-delivery promise.

## Transaction ownership and observability

The router, adapter, client lookup and resolver call neither `commit`,
`rollback`, `begin` nor `flush`. Only `ProviderInboundMessageCoordinator`
controls transaction completion when it is invoked. Signature rejection and
all pre-core business outcomes must occur before receipt claim.

Observability may expose stable status/resolution source and safe identifiers
(`MessageSid`, channel/client/commerce ids when resolved). It must not expose
the auth token, signature header, raw `Body`, or full form payload.

## Expected files

- `requirements.txt`
- `backend/config/settings.py`
- `backend/services/twilio_inbound_adapter.py`
- `backend/routers/twilio_webhook.py`
- `backend/main.py`
- focused tests under `backend/tests/`
- `openspec/changes/add-twilio-inbound-webhook-5-5/` artifacts and spec delta

## Validation and rollback

Run focused adapter/router/settings/core-boundary tests, Ruff and `compileall`
on touched Python files, strict OpenSpec validation and `git diff --check`.
There is no migration. Rollback removes the router registration, adapter,
settings/dependency entry and tests; existing 5.1–5.4 persistence and local
endpoint behavior remain unchanged.

## Deferred limitations

Phase 5.6 owns durable outgoing response delivery, delivery callbacks, retry
policy and response replay. Shared-channel code/manual-selection conversation
integration is intentionally not implied by this transport ingress.

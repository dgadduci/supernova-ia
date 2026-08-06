## Why

Phase 5.5 acknowledges a first inbound Twilio delivery with TwiML, but it does
not preserve or send the business responses produced by the existing message
pipeline. Consequently, a successful inbound receipt has no durable outbound
work item, no provider message identity and no delivery-status audit trail.

## Objective

Add a durable, provider-neutral outbound-message outbox for responses produced
by the Phase-5.4 transaction; a Twilio sender that dispatches pending rows;
and a signature-validated Twilio status callback that records provider delivery
state. Transient provider failures remain retryable without re-running the
inbound pipeline or rebuilding customer responses.

## Current execution path

The Phase-5.4 `ProviderInboundMessageCoordinator` claims an inbound receipt,
obtains a compatible session, invokes `process_incoming_message(...)`, and
commits once. It returns `ProcessedIntent` values but does not construct
`CustomerResponse` values. The local HTTP endpoint instead calls
`process_incoming_message_with_responses(...)`, which commits business work
first and then constructs responses in memory. Phase 5.5 converts a signed
Twilio inbound form into the 5.4 command and returns acknowledgement/duplicate/
control TwiML only; it has no outbound REST client, callback route or retry
state.

## Scope

- Add one durable outbound-message model with immutable destination, body,
  provider, inbound receipt reference, ordered response sequence, provider SID
  when accepted, attempt count, retry eligibility and terminal/delivery state.
- Refactor only the reusable response construction necessary for 5.4 to stage
  the same customer-facing responses and their outbox rows inside its existing
  single transaction.
- Add a provider-neutral dispatch service and a Twilio REST adapter. A pending
  row is leased/claimed transactionally, then the network call happens outside
  that claim transaction; the result is recorded conditionally by the lease.
- Add a bounded explicit retry entry point (not a background scheduler) for
  due retryable rows, and a signed Twilio callback route that records only
  monotonic provider delivery transitions for the matching Twilio SID.
- Update 5.5 so first processing returns empty TwiML after the durable outbox
  commit; no business response is embedded in TwiML.
- Add focused tests, migration, permanent OpenSpec capability and settings for
  outbound/callback configuration.

## Non-goals

- No new inbound receipt rule, second business pipeline, change to client or
  commerce routing, shared-channel conversation integration, customer creation,
  catalog/recognition/order redesign, or LangGraph.
- No worker daemon, Celery/queue broker, cron scheduler, operator UI, bulk
  campaign, media/attachments, templates, read receipts, opt-out handling or
  delivery analytics.
- No guaranteed exactly-once provider API call: network ambiguity may cause a
  provider-side duplicate. The system guarantees no inbound reprocessing and
  one active dispatch lease per durable outbox row.

## Shared boundary, outcomes and fallback

| Condition | Durable outcome | Fallback |
| --- | --- | --- |
| First valid inbound processing | Ordered pending rows commit with receipt/session/pipeline effects | none |
| Duplicate inbound receipt | No new outbox rows | no replay from webhook |
| Twilio accepts send | Store returned provider SID; state `accepted` | none |
| Retryable transport/5xx/429 failure before acceptance | Keep one row retryable with bounded backoff | later explicit dispatcher run |
| Definitive provider 4xx or retry budget exhausted | `failed_terminal` with safe provider code/category | no silent resend |
| Signed callback advances status | Persist monotonic status/timestamp | ignore stale/regressive callback |
| Invalid signature/unknown SID/mismatched provider | no mutation; `403` for signature, `204` for unknown valid callback | no lookup by phone/body |

The authoritative source for a business response is the durable outbound row,
not TwiML and not a re-run of the response builder. A callback never creates a
row, schedules a retry or triggers the pipeline. A transport failure never
falls back to TwiML, another channel, another commerce, a new receipt, or a
new customer response.

## Transaction ownership and observability

The Phase-5.4 coordinator remains the owner of the one inbound transaction;
response building and outbox staging must not commit or roll back. Dispatch
claim/finalization operations own only their narrow persistence transactions;
the Twilio adapter owns no database transaction. The callback route owns no
transaction control and delegates state mutation to its service boundary.

Log only stable IDs and status/category: inbound receipt id, outbox id, Twilio
SID, attempt count and transition. Never log auth tokens, signatures, raw
inbound text, outbound body or complete callback form.

## Expected files

- `backend/models/` and one Alembic revision for the outbox
- `backend/repositories/` and `backend/services/` for staging, dispatch and
  Twilio delivery/callback adapters
- `backend/intents/orchestration/` response-boundary extraction
- `backend/routers/twilio_webhook.py`, one callback router, settings and
  application registration
- focused tests under `backend/tests/`
- this change's OpenSpec artifacts and spec delta

## Validation and rollback

Run focused outbox/coordinator/dispatch/callback/webhook/settings tests, Ruff
and `compileall` on touched Python files, strict OpenSpec validation and
`git diff --check`. The migration adds only the outbox table and indexes.
Rollback removes outbound routes/dispatch entry point and the table after
confirming no pending rows need retention; Phase 5.4/5.5 inbound processing
remains available and continues to return empty acknowledgement TwiML.

## Deferred limitations

Actual scheduling, operational redrive UI, media/templates, customer delivery
preferences and provider-wide analytics are intentionally deferred.

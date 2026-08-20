# Design: commerce edge observability

## Decision

Use the existing NovaOrders JSON event contract for the core ingress and a
small dependency-free adapter-local equivalent for T-C. Do not change the
process-wide Uvicorn formatter: changing every adapter log record would widen
the privacy and operational surface unnecessarily. Only the already bounded
inbound outcome calls become structured events.

## Event contract

Event name: `commerce_installation_inbound_outcome`.

Components:

- Core: `commerce_installation_ingress`.
- Adapter: `commerce_installation_adapter`.

The core event catalogue/parser must accept exactly these two component values
for this event so `backend/cli/query_production_logs.py` can parse logs from
either Railway service. The adapter still builds the line locally and does not
import `backend.*`; accepting its bounded component is a catalogue rule, not a
runtime dependency.

Outcomes:

- `accepted` — the core coordinator accepted a new receipt.
- `duplicate` — the coordinator found an already processed provider message.
- `rejected` — a closed business or validation condition prevented acceptance.
- `unreachable` — the adapter could not obtain a usable core result.

Reason tokens:

`signature_rejected`, `invalid_form`, `missing_comercio_id`,
`core_http_failure`, `core_invalid_response`, `unknown_destination`,
`shared_channel_not_supported`, `channel_commerce_mismatch`,
`unknown_client`, `unavailable_commerce`, and `invalid_context`.

The `reason` field is required for `rejected` and `unreachable`, and absent for
`accepted` and `duplicate`. The emitter validates this closed pair rather than
accepting arbitrary text. HTTP status may be retained only as a bounded
integer in the adapter event for `unreachable`; it is not a business reason.

## Core emission

Extend `backend/observability/events.py` with the event catalogue entry,
component, outcome allowlist, reason allowlist and optional-field validation.
The router calls the existing `emit_event` helper after each validated business
branch: unknown destination, shared channel, commerce mismatch, unknown client,
unavailable commerce, accepted, duplicate and invalid context. The JSON event
is emitted after the typed response is built and before returning it. Existing
`logger.info` calls may be removed once the structured event covers their safe
fields; no raw fields are added to the event.

The router does not emit this commerce-outcome event for pre-decision HTTP
branches: unknown/inactive installation, missing or undecryptable master or
installation key material, signature failure, or canonical payload
validation/identity mismatch. Those branches retain their current HTTP
responses and are not reclassified as business rejections. When the request
comes through the adapter, its non-200 response is represented by the adapter
as `unreachable` with the bounded `core_http_failure` reason.

## Adapter emission

Add `commerce_adapter/app/observability.py` with a pure event builder and a
single-write emitter accepting only the closed outcome/reason/status fields.
It must not import `backend.*`. The emitter writes compact JSON with stable
key ordering to stdout and swallows serialization/write errors. The webhook
route calls it after signature rejection, invalid form, missing commerce id,
core unreachable, accepted/duplicate, core rejection and typed-but-unknown
response branches. Existing response status and TwiML remain untouched.

The adapter is the observability owner for the transport boundary. A core
non-2xx response is `unreachable/core_http_failure`; a 200 response that is
not a usable typed result is `unreachable/core_invalid_response`. The adapter
must not infer a business rejection from either condition.

## Privacy and failure rules

No event accepts message SID, installation ID, commerce ID, receipt ID, phone,
body, profile name, token, signature, URL, credential, provider code or raw
exception text. The installation and commerce can still be correlated by
Railway service and request timestamp; a future correlation identifier needs a
separate approved contract. Event emission is best effort and cannot throw
into the business path.

## Test seams

The adapter emitter receives an injectable text sink so tests can capture one
line without intercepting the process-wide logger. The core tests use the
existing `emit_event` sink seam and `parse_event` to assert the canonical
contract. Route tests assert that every existing result branch emits exactly
one event, that pre-decision core HTTP failures do not create a core
business-outcome event, and that the HTTP/TwiML response is unchanged. The
production-log parser tests cover both documented component values and reject
unknown ones.

## Deployment and rollback

No migration or secret change is required. Deploy core and adapter together so
the event vocabulary is available at both edges. If the event sink is broken,
the request remains governed by the existing typed outcome; reverting the
event calls restores the pre-change log surface without data repair.

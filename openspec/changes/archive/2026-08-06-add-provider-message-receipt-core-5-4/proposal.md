## Why

Phases 5.1–5.3 establish provider-channel routing and an explicit,
channel-scoped commerce selection, but deliberately do not process a provider
message. The current local endpoint already runs the business pipeline, yet it
requires a known commerce/client session and `process_incoming_message_transactional`
owns a standalone commit. It cannot atomically claim a provider receipt,
obtain the conversation session and process the message exactly once.

## Objective

Add a provider-neutral, transaction-owning inbound-message core. For a
caller-supplied, already validated routing decision it shall claim one opaque
provider receipt, ensure the active conversation session, invoke the existing
message pipeline, and atomically commit all staged work exactly once. A
duplicate committed receipt shall never invoke the pipeline again.

## Current execution path

`POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages`
obtains an existing active `Session` through `SessionService.get_active()` and
calls `process_incoming_message_with_responses()`. That response orchestrator
calls `process_incoming_message_transactional()`, which commits or rolls back
by itself. `SessionService.create()` also owns commits. Neither boundary can
participate safely in a wider provider-receipt transaction.

## Scope

- Add a durable provider-message receipt model with a unique
  `(provider, receipt_id)` identity, restricted foreign keys to the selected
  channel, client and commerce, and the minimum audit metadata required to
  prove a committed claim.
- Add a provider-neutral coordinator that receives a validated active routing
  decision (`provider`, opaque receipt id, `canal_id`, `cliente_id`,
  `comercio_id`, raw message) and owns the sole transaction for receipt claim,
  active-session acquisition/creation and existing pipeline execution.
- Extract or expose only the caller-owned staging necessary to obtain an
  active `Session`; preserve the existing local endpoint's public behavior.
- Return immutable typed outcomes for `processed`, `already_processed`,
  `invalid_context` and technical failure propagation. The coordinator is not
  an HTTP, provider-SDK or response-delivery boundary.
- Add focused migration, repository/service/coordinator tests and a permanent
  OpenSpec capability.

## Non-goals

- No FastAPI route, Twilio SDK, signature validation, TwiML, provider payload
  parsing, client lookup/creation by phone, routing-code parsing, manual
  selection UI, outbound delivery, callback state, retry scheduling or replay
  of outbound responses.
- No change to the rules from phases 5.1–5.3: callers must supply an existing
  active client and an authoritative channel-scoped commerce decision. The
  coordinator does not infer, widen or silently switch commerce.
- No recognizer, classifier, handler, catalog, pending-context, order or
  product-recognition redesign; no LangGraph; no unrelated migrations.

## Authoritative outcomes and fallback

| Condition | Outcome | Required behavior |
| --- | --- | --- |
| First valid receipt and validated active routing decision | `processed` | Stage receipt, active session and existing pipeline; commit once |
| Previously committed `(provider, receipt_id)` | `already_processed` | No session creation, pipeline invocation or mutation |
| Missing/inactive client/channel/commerce, mismatched channel membership, or invalid input | `invalid_context` | No receipt or business mutation |
| Database/pipeline failure | exception propagates | Roll back the whole coordinator transaction; do not leave a receipt claim |

There is no business fallback. A duplicate must not reprocess the message, and
an invalid routing decision must not fall back to an existing session, a
client-only context, another commerce or the local HTTP endpoint.

## Transaction ownership and observability

The Phase-5.4 coordinator is the only new boundary allowed to call `commit`
or `rollback`. It commits once only after receipt, session and pipeline staging
succeed, and rolls back once for an exception. Repositories, routing services,
session staging helpers and the extracted non-transactional pipeline call no
transaction-control methods. The existing local endpoint remains behaviorally
compatible and continues to use an appropriate transaction-owning wrapper.

Typed outcomes expose only safe IDs, receipt identity, status and a stable
`resolution_source`; raw inbound text must not be placed in outcome/log
metadata. The durable receipt may retain only the opaque receipt identity and
safe relational audit fields, not an outbound delivery contract.

## Expected files

- `backend/models/recepcion_mensaje_proveedor.py`
- `backend/models/__init__.py`
- one new revision under `backend/alembic/versions/` for provider receipts
- `backend/repositories/recepcion_mensaje_proveedor_repository.py`
- `backend/services/provider_inbound_message_coordinator.py`
- `backend/services/session_service.py` and/or
  `backend/repositories/session_repository.py`
- `backend/intents/orchestration/transactional_message_processor.py`
- `backend/intents/orchestration/incoming_message_response_orchestrator.py`
- focused tests under `backend/tests/`
- this change's OpenSpec artifacts and spec deltas

## Validation and rollback

Run focused provider-receipt/core, existing transactional-processor and
incoming-message endpoint tests; Ruff and `compileall` on touched files;
strict OpenSpec validation; and `git diff --check`. The migration adds only
the receipt table and its indexes/constraints. Downgrade removes that table
without rewriting pre-existing sessions, contexts, orders or messages.

## Deferred limitations

Phase 5.5 owns signature-validated Twilio HTTP ingress and conversion from a
provider payload into this core's validated input. Phase 5.6 owns response
delivery, callback states, retries and any response replay policy.

## Decision

Phase 5.4 introduces one provider-neutral coordinator, not a parallel message
pipeline. Its input is a validated `ProviderInboundMessageCommand` (name may
vary) containing: provider identifier, opaque receipt identifier, channel id,
existing client id, authoritative commerce id and raw message. Phase 5.5 is
responsible for deriving that command from Twilio only after signature
validation; it must not duplicate transaction or idempotency logic.

The coordinator validates, in this order:

1. input shape and non-empty raw message/receipt identity;
2. existing active client;
3. active channel and channel-scoped authority for the supplied commerce:
   dedicated ownership, or an existing selected shared-channel context;
4. receipt claim;
5. active conversation session acquisition or staged creation for exactly that
   commerce/client pair;
6. the existing non-transactional message pipeline.

It is the sole owner of the database transaction. The existing transactional
wrapper remains the compatibility owner for the local endpoint, but is
refactored to call the same non-transactional pipeline primitive used by 5.4.

## Receipt persistence and concurrency

`RecepcionMensajeProveedor` (exact final name may follow repository naming)
contains an internal primary key; normalized provider; opaque receipt id;
`canal_id`, `cliente_id`, `comercio_id`; and committed timestamp. It has a
database unique constraint on `(provider, receipt_id)` and restrictive foreign
keys. It stores no outbound response, retry state or raw message body.

The repository claims the receipt with a PostgreSQL conflict-safe insert (for
example `INSERT ... ON CONFLICT DO NOTHING RETURNING`) rather than a
check-then-insert race. A lost claim returns `already_processed` only after
the winner's transaction is committed; a failed winner rolls back its insert,
allowing a later attempt to become the first valid claim. The coordinator must
not translate arbitrary database failures into `already_processed`.

## Session and pipeline boundary

The coordinator must not use a `SessionService` method that commits. It may
use a new caller-owned `get_or_create_active_staged` operation (or equivalent
minimal repository/service extraction) that reuses the existing active-session
constraint and stages creation without committing. It must never adopt a
session from a different commerce or client.

Extract the invocation currently inside
`process_incoming_message_transactional()` into a non-transactional reusable
operation, preserving validation, dispatch and diagnostics semantics. The
5.4 coordinator invokes it inside its transaction. The existing local response
orchestrator keeps its current public behavior through its existing
transactional wrapper; response construction remains after successful
pipeline processing and is not persisted as a receipt result.

## State and outcomes

| State | Condition | Mutation | Result |
| --- | --- | --- | --- |
| Invalid | Input/routing validation fails | None | `invalid_context` |
| Duplicate | Receipt already committed | None | `already_processed` |
| First valid | Receipt claim succeeds and pipeline succeeds | Receipt + compatible active session + existing pipeline effects | `processed` |
| Failed | Any DB/pipeline exception after transaction start | Full rollback | Exception propagates |

`processed` is authoritative only after the single commit succeeds. No valid
business outcome may invoke fallback processing. A duplicate must not rebuild
customer responses or trigger the pipeline because outbound response replay is
deferred to 5.6.

## Invariants

- Fuzzy remains the recognition fallback; Phase 5.4 does not alter recognition.
- The supplied commerce must be channel-authoritative; a shared pending target
  is never processing authority.
- The receipt uniqueness boundary is provider plus opaque provider receipt id,
  never raw message text or customer identity.
- Exactly one coordinator owns `commit`/`rollback`; repositories and staging
  helpers own neither.
- A rollback leaves neither a receipt claim nor a newly staged conversation
  session/pipeline effect durable.
- No Phase-5.4 component calls a webhook/router, outbound provider client or
  delivery callback.

## Focused tests

1. First valid dedicated routing processes once, persists one receipt and
   creates/reuses only the matching active session.
2. Valid selected shared context processes only its selected commerce; absent,
   stale or pending-only context is `invalid_context` with no mutation.
3. Duplicate receipt returns `already_processed` and proves no pipeline/session
   call or extra receipt row.
4. Concurrent/conflicting claim follows the unique receipt boundary and does
   not double-process.
5. Pipeline/database failure rolls back receipt, staged session and pipeline
   effects; exceptions propagate.
6. Existing local incoming-message behavior and diagnostics remain covered.
7. Static boundaries prove transaction control exists only in the two allowed
   transaction owners and no HTTP/provider/delivery path is invoked.

## Validation

```bash
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_provider_message_receipt_core.py backend/tests/test_transactional_message_processor.py backend/tests/test_incoming_message_orchestrator.py backend/tests/test_incoming_messages_endpoint.py
PYTHONPATH=. venv/bin/python -m ruff check backend/models/recepcion_mensaje_proveedor.py backend/repositories/recepcion_mensaje_proveedor_repository.py backend/services/provider_inbound_message_coordinator.py backend/services/session_service.py backend/repositories/session_repository.py backend/intents/orchestration/transactional_message_processor.py backend/intents/orchestration/incoming_message_response_orchestrator.py backend/tests/test_provider_message_receipt_core.py
PYTHONPATH=. venv/bin/python -m compileall backend/models/recepcion_mensaje_proveedor.py backend/repositories/recepcion_mensaje_proveedor_repository.py backend/services/provider_inbound_message_coordinator.py backend/services/session_service.py backend/repositories/session_repository.py backend/intents/orchestration/transactional_message_processor.py backend/intents/orchestration/incoming_message_response_orchestrator.py backend/tests/test_provider_message_receipt_core.py
openspec validate add-provider-message-receipt-core-5-4 --strict
git diff --check
```

Record exact outputs in `tasks.md`.
